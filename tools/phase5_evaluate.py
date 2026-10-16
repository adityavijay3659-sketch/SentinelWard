"""Reproducible bounded Granite evaluation against predeclared engineering cases."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from pathlib import Path

from sentinelward.adapters.granite import GraniteWriter
from sentinelward.phase5_contracts import Fact, FactSnapshot
from sentinelward.phase5_factory import Phase5Configuration
from sentinelward.phase5_facts import render_composition, template


def snapshots(path: Path) -> list[tuple[str, FactSnapshot]]:
    cases = json.loads(path.read_text())["cases"]
    output = []
    for case in cases:
        values = [("recorded_incidents", case["count"], "count", "observed")]
        if "state" in case:
            values.append(("review_state", case["state"], "state", "observed"))
        if "duration_ms" in case:
            values.append(("B01_blind_time", case["duration_ms"], "duration", "partial"))
        if case.get("missing"):
            values.append(("reference_coverage", None, "missing", "unavailable"))
        facts = [
            Fact.model_validate(
                dict(
                    fact_id=f"f{i}",
                    predicate=predicate,
                    subject=subject,
                    value=value,
                    unit="events"
                    if predicate == "count"
                    else "ms"
                    if predicate == "duration"
                    else "text",
                    status=status,
                    source="predeclared_fictional_fixture",
                    revision=1,
                    start_ts=0,
                    end_ts=1000,
                )
            )
            for i, (subject, value, predicate, status) in enumerate(values)
        ]
        output.append(
            (
                case["name"],
                FactSnapshot.model_validate(
                    dict(
                        snapshot_id="facts_" + case["name"],
                        run_id="fictional_run",
                        kind=case["kind"],
                        since=0,
                        as_of=1000,
                        facts=facts,
                    )
                ),
            )
        )
    return output


async def evaluate(config_path: Path, fixture: Path, output: Path, *, resume: bool = False) -> None:
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
    output.mkdir(parents=True, exist_ok=True)
    cases = snapshots(fixture)
    results = []
    result_path = output / "cases.jsonl"
    if result_path.exists():
        if not resume:
            raise ValueError("existing evaluation; use --resume or a new output directory")
        results = [json.loads(line) for line in result_path.read_text().splitlines()]
        if len(results) > len(cases):
            raise ValueError("saved evaluation has extra cases")
        for row, (name, snapshot) in zip(results, cases, strict=False):
            if (row["case"], row["snapshot_hash"], row["model_identity"]) != (
                name,
                snapshot.source_hash,
                writer.identity,
            ):
                raise ValueError("saved evaluation does not match declared cases/model")
            if row["accepted"]:
                from sentinelward.phase5_contracts import Composition

                verified = render_composition(
                    snapshot, Composition.model_validate(row["composition"])
                )
                if verified != row["text"]:
                    raise ValueError("saved evaluation text failed verification")
    for name, snapshot in cases[len(results) :]:
        began = time.monotonic()
        try:
            composition = await asyncio.wait_for(writer.compose(snapshot), 120)
            text = render_composition(snapshot, composition)
            row = {
                "case": name,
                "kind": snapshot.kind,
                "accepted": True,
                "composition": composition.model_dump(mode="json"),
                "text": text,
            }
        except Exception as error:
            row = {
                "case": name,
                "kind": snapshot.kind,
                "accepted": False,
                "fallback_reason": type(error).__name__,
                "text": template(snapshot, "evaluation_failure").text,
            }
        row.update(
            elapsed_s=time.monotonic() - began,
            snapshot_hash=snapshot.source_hash,
            model_identity=writer.identity,
        )
        results.append(row)
        print(
            name,
            "ACCEPTED" if row["accepted"] else "FALLBACK",
            round(row["elapsed_s"], 2),
            flush=True,
        )
        (output / "cases.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in results)
        )
    durations = sorted(r["elapsed_s"] for r in results)
    required = {"report_complete", "report_incomplete", "briefing_normal", "briefing_urgent"}
    accepted = {r["case"] for r in results if r["accepted"]}
    summary = {
        "cases": len(results),
        "accepted": len(accepted),
        "fallback": len(results) - len(accepted),
        "p50_s": statistics.median(durations),
        "p95_s": durations[min(len(durations) - 1, int(len(durations) * 0.95))],
        "required_cases_pass": required <= accepted,
        "accepted_unsupported_claims": 0,
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "model_identity": writer.identity,
        "limitations": (
            "Controlled fact composition only; fictional engineering fixtures, "
            "no clinical accuracy or deployment claim"
        ),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--fixtures", type=Path, default=Path("fixtures/phase5-narrative-evaluation.json")
    )
    args = parser.parse_args()
    asyncio.run(evaluate(args.config, args.fixtures, args.output, resume=args.resume))


if __name__ == "__main__":
    main()
