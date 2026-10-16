"""Run python -m tools.phase5_acceptance; fallback always fails this source-only gate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path

from sentinelward.adapters.granite import GraniteWriter
from sentinelward.phase5_contracts import Composition, FactSnapshot
from sentinelward.phase5_factory import Phase5Configuration
from sentinelward.phase5_facts import render_composition
from tests.phase5_workflows import make_workflow


async def evaluate(config_path: Path, fixture: Path, output: Path, *, resume: bool) -> bool:
    config = Phase5Configuration.model_validate_json(config_path.read_bytes())
    assert config.writer is not None
    with config.writer.model_file.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    assert actual == config.writer.model_sha256
    writer = GraniteWriter(
        config.writer.base_url,
        config.writer.model,
        actual,
        config.writer.build,
        config.writer.api_key,
    )
    definition = json.loads(fixture.read_text())
    fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    cases = [
        (case, repeat, False)
        for repeat in range(definition["required_repetitions"])
        for case in definition["cases"]
    ]
    cases += [(case, 0, True) for case in definition["scheduled_cases"]]
    output.mkdir(parents=True, exist_ok=True)
    path = output / "cases.jsonl"
    rows = []
    if path.exists():
        if not resume:
            raise ValueError("existing results require --resume or new output directory")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if len(rows) > len(cases):
            raise ValueError("unexpected saved cases")
        for row, (case, repeat, scheduled) in zip(rows, cases, strict=False):
            assert (
                row["case"],
                row["repeat"],
                row["scheduled"],
                row["fixture_sha256"],
                row["model_identity"],
            ) == (case["name"], repeat, scheduled, fixture_hash, writer.identity)
            if row["accepted"]:
                snapshot = FactSnapshot.model_validate(row["snapshot"])
                assert (
                    render_composition(snapshot, Composition.model_validate(row["composition"]))
                    == row["text"]
                )
    for case, repeat, scheduled in cases[len(rows) :]:
        began = time.monotonic()
        row = {
            "case": case["name"],
            "repeat": repeat,
            "scheduled": scheduled,
            "fixture_sha256": fixture_hash,
            "model_identity": writer.identity,
            "accepted": False,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="phase5-acceptance-") as folder:
                agent, key, snapshot = await make_workflow(
                    Path(folder), case, writer, scheduled=scheduled
                )
                assert await agent.process_one_job()
                state = await agent.status()
                record = next(r for r in state["records"][case["kind"]] if r["record_id"] == key)
                job = next(j for j in state["jobs"] if j["record_id"] == key)
                narrative = record["narrative"]
                elapsed = (job["completed_ts"] - job["queued_ts"]) / 1000
                accepted = (
                    job["state"] == "accepted"
                    and narrative["generator"] == "granite"
                    and elapsed <= case["budget_s"]
                )
                composition = Composition.model_validate(narrative["composition"])
                assert render_composition(snapshot, composition) == narrative["text"]
                assert case["kind"] != "briefing" or bool(record["urgent"]) == case["urgent"]
                row.update(
                    accepted=accepted,
                    job=job,
                    fact_count=len(snapshot.facts),
                    snapshot=snapshot.model_dump(mode="json"),
                    composition=composition.model_dump(mode="json"),
                    text=narrative["text"],
                    end_to_end_s=elapsed,
                    budget_s=case["budget_s"],
                )
        except Exception as exc:
            row.update(error_class=type(exc).__name__)
        row["elapsed_s"] = time.monotonic() - began
        rows.append(row)
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        print(
            case["name"],
            repeat,
            "ACCEPTED" if row["accepted"] else "FAILED",
            round(row["elapsed_s"], 2),
            flush=True,
        )
    elapsed = sorted(r["elapsed_s"] for r in rows)
    summary = {
        "required": len(cases),
        "accepted": sum(r["accepted"] for r in rows),
        "failed": sum(not r["accepted"] for r in rows),
        "pass": all(r["accepted"] for r in rows),
        "p50_s": statistics.median(elapsed),
        "p95_s": elapsed[min(len(elapsed) - 1, int(0.95 * len(elapsed)))],
        "fixture_sha256": fixture_hash,
        "model_identity": writer.identity,
        "scope": "Local full fictional workflows; controlled composition; no clinical validation",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return summary["pass"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fixtures", type=Path, default=Path("fixtures/phase5-full-workflow-acceptance.json")
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not asyncio.run(evaluate(args.config, args.fixtures, args.output, resume=args.resume)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
