"""Local Phase 5 host-contention check, not full simulator/MQTT/M6 acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path

from sentinelward.adapters.granite import GraniteWriter, UnavailableWriter
from sentinelward.contracts import RecordMessage, parse_wire_message
from sentinelward.phase5_factory import Phase5Configuration
from sentinelward.phase5_presentation import record_views
from tests.phase5_workflows import make_workflow
from tests.test_phase4 import control
from tests.test_phase5 import lab, routed_alert


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


async def evaluate(config_path: Path, output: Path) -> bool:
    config = Phase5Configuration.model_validate_json(config_path.read_bytes())
    assert config.writer is not None
    with config.writer.model_file.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == config.writer.model_sha256
    writer = GraniteWriter(
        config.writer.base_url,
        config.writer.model,
        config.writer.model_sha256,
        config.writer.build,
        config.writer.api_key,
    )
    fixture = json.loads(Path("fixtures/phase5-full-workflow-acceptance.json").read_text())[
        "cases"
    ][-1]
    results = []
    # Predeclared alternating order; no picking the fastest individual run.
    for repetition in range(3):
        for model_enabled in (False, True) if repetition % 2 == 0 else (True, False):
            with tempfile.TemporaryDirectory(prefix="phase5-load-") as directory:
                root = Path(directory)
                _context, _key, snapshot = await make_workflow(root / "facts", fixture, writer)
                agent, phase4, alerts, now, store = await lab(root / "runtime")
                sample = phase4.inventory["MON-01"]
                phase4.inventory = {
                    f"MON-{i:02}": sample.model_copy(
                        update={
                            "bed_id": f"B{i:02}",
                            "device_id": f"MON-{i:02}",
                            "username": f"MON-{i:02}",
                            "client_id": f"MON-{i:02}",
                        }
                    )
                    for i in range(1, 13)
                }
                agent.writer = UnavailableWriter()
                background = None
                if model_enabled:
                    background = asyncio.create_task(writer.compose(snapshot))
                    # Let the actual HTTP request start; no inferred warmup baseline.
                    await asyncio.sleep(0.1)
                durations = []
                started = time.monotonic()
                for second in range(1201):
                    now[0] = 1_000_000 + second * 1000
                    tick = time.perf_counter()
                    await phase4.advance()
                    if second == 60:
                        await routed_alert(agent, alerts, now, "load_urgent")
                    await agent.advance()
                    durations.append((time.perf_counter() - tick) * 1000)
                    await asyncio.sleep(0)
                state = await agent.status()
                p4state = await phase4.snapshot()
                assert set(p4state["offline"]) >= {"B03", "B04", "B07"}
                assert not state["runtime"]["active"]
                assert len(state["records"]["briefing"]) == 1
                assert state["records"]["briefing"][0]["urgent"]
                async with agent.repository.transaction() as unit:
                    ledger = len(unit.list("coverage"))
                for event in store.outbox.values():
                    topic = event["payload"]["topic"]
                    parsed = parse_wire_message(
                        topic, json.dumps(event["payload"]["body"]).encode()
                    )
                    assert parsed.type != "score"
                    if isinstance(parsed, RecordMessage):
                        assert len(record_views(parsed).user) <= 160
                now[0] += 1000
                await phase4.handle_control(control("reset", "runA", now[0]))
                now[0] += 1000
                await phase4.handle_control(control("run", "runB", now[0]))
                assert not (await agent.status())["records"]["briefing"]
                if background is not None:
                    await asyncio.wait_for(background, 120)
                results.append(
                    {
                        "repeat": repetition,
                        "model_enabled": model_enabled,
                        "logical_seconds": 1200,
                        "ticks": len(durations),
                        "beds": 12,
                        "tick_p50_ms": statistics.median(durations),
                        "tick_p95_ms": percentile(durations, 0.95),
                        "max_tick_ms": max(durations),
                        "wall_s": time.monotonic() - started,
                        "ledger_rows": ledger,
                        "model_composition_valid": True if background else None,
                    }
                )
                print(json.dumps(results[-1]), flush=True)
    baseline = statistics.median(r["tick_p95_ms"] for r in results if not r["model_enabled"])
    enabled = statistics.median(r["tick_p95_ms"] for r in results if r["model_enabled"])
    passed = enabled <= baseline * 1.10
    summary = {
        "pass": passed,
        "baseline_median_p95_ms": baseline,
        "model_median_p95_ms": enabled,
        "relative_change_pct": 100 * (enabled / baseline - 1),
        "runs": results,
        "scope": (
            "Accelerated Phase 5 lifecycle/ledger, actual concurrent Granite; "
            "excludes vitals/MQTT/M6/UI and whole-team timing acceptance."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "runs"}), flush=True)
    return passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not asyncio.run(evaluate(args.config, args.output)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
