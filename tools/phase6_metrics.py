"""Summarize an observer capture against the declared run, without inferring clinical truth."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tools.phase6_acceptance import ROOT, digest, fresh_output, write_json


def distribution(values: list[float]) -> dict[str, float | int | None]:
    values = sorted(values)
    return {
        "n": len(values),
        "p50": statistics.median(values) if values else None,
        "p95": values[max(0, math.ceil(len(values) * 0.95) - 1)] if values else None,
        "max": max(values) if values else None,
    }


def summarize(observer: Path, event_files: list[Path]) -> dict[str, Any]:
    summary = json.loads((observer / "observation-summary.json").read_text("utf-8"))
    for name in ("wire.jsonl", "probes.jsonl"):
        if digest(observer / name) != summary["files"][name]:
            raise ValueError("observer file changed after capture")
    run_id = summary["run_id"]
    events = []
    for path in event_files:
        for line in path.read_text("utf-8").splitlines():
            row = json.loads(line)
            if not {"run_id", "t_s", "ts", "bed_id", "event", "detail"} <= row.keys():
                raise ValueError("producer event missing locked contract fields")
            if row["run_id"] == run_id:
                if type(row["ts"]) is not int or not isinstance(row["t_s"], (int, float)):
                    raise ValueError("invalid event clock")
                if not math.isfinite(row["t_s"]) or row["t_s"] < 0:
                    raise ValueError("invalid relative time")
                events.append(row)
    starts = {row["ts"] for row in events if row["event"] == "run_start" and row["t_s"] == 0}
    if len(starts) != 1:
        return {
            "status": "BLOCKED",
            "run_id": run_id,
            "reason": "one unambiguous declared run_start at t_s=0 is required",
        }
    start = starts.pop()
    scenario = json.loads((ROOT / "fixtures/phase6-scenario.json").read_text("utf-8"))
    duration = scenario["duration_s"]
    frames: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scores: dict[str, Counter[str]] = defaultdict(Counter)
    seen_scores: dict[tuple[str, int, int, str], str] = {}
    repeated_scores = conflicting_scores = 0
    score_delay: list[float] = []
    negative_delay = stale = invalid = 0
    for line in (observer / "wire.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if row["validation"] != "VALID":
            invalid += 1
            continue
        if row.get("identity_matches_observed_run") is False:
            stale += 1
            continue
        if row.get("type") == "vitals":
            if start <= row["ts"] < start + duration * 1000:
                frames[row["bed_id"]].append(row)
        elif (
            row.get("type") == "score"
            and row.get("model") == "M6"
            and row.get("demo_run_id") == run_id
        ):
            key = (row["bed_id"], row["window_start"], row["window_s"], row["model_version"])
            if key in seen_scores:
                repeated_scores += 1
                conflicting_scores += int(seen_scores[key] != row["payload_sha256"])
                continue
            seen_scores[key] = row["payload_sha256"]
            scores[row["bed_id"]]["label:" + row["label"]] += 1
            scores[row["bed_id"]]["path:" + str(row.get("assessment_path"))] += 1
            delay = (row["received_ts"] - row["window_start"] - row["window_s"] * 1000) / 1000
            if delay < 0:
                negative_delay += 1
            else:
                score_delay.append(delay)
    patients = []
    for bed in scenario["bed_ids"]:
        join = scenario["join_s"].get(bed, 0)
        end = scenario["source_end_s"].get(bed, duration)
        rows = frames[bed]
        active = [r for r in rows if join <= (r["ts"] - start) / 1000 < end]
        timestamps = {r["ts"] for r in active}
        covered = {int((ts - start) // 1000) for ts in timestamps}
        unique = {(r["seq"], r["ts"]) for r in active}
        previous = -1
        reordered = 0
        for row in active:
            if row["ts"] < previous:
                reordered += 1
            previous = max(previous, row["ts"])
        patients.append(
            {
                "bed_id": bed,
                "expected_source_seconds": end - join,
                "received_vitals": len(rows),
                "active_interval_vitals": len(active),
                "outside_source_interval_vitals": len(rows) - len(active),
                "unique_seq_timestamp_pairs": len(unique),
                "duplicate_seq_timestamp_pairs": len(active) - len(unique),
                "covered_source_seconds": len(covered),
                "unobserved_source_seconds": end - join - len(covered),
                "source_seconds_coverage_pct": 100 * len(covered) / (end - join),
                "out_of_order_timestamp_receipts": reordered,
                "m6_counts": dict(scores[bed]),
            }
        )
    probes: dict[str, list[float]] = defaultdict(list)
    failures: Counter[str] = Counter()
    resources = []
    for line in (observer / "probes.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if "id" not in row:
            resources.append(row)
        else:
            probes[row["id"]].append(row["elapsed_ms"])
            if row.get("status_code") != 200:
                failures[row["id"]] += 1
    complete_span = (
        summary["capture_start_ts"] <= start
        and summary["capture_end_ts"] >= start + duration * 1000
    )
    run_end = any(row["event"] == "run_end" and row["t_s"] >= duration for row in events)
    status = "PASS" if complete_span and run_end and summary["status"] == "PASS" else "BLOCKED"
    if summary["status"] == "FAIL":
        status = "FAIL"
    return {
        "schema_version": 1,
        "status": status,
        "run_id": run_id,
        "scope": "Capture/coverage diagnostics only; no model, backend or UI acceptance inferred",
        "run_start_ts": start,
        "capture_spans_declared_run": complete_span,
        "producer_run_end_present": run_end,
        "patients": patients,
        "expected_vitals_frames": sum(row["expected_source_seconds"] for row in patients),
        "unobserved_source_seconds": sum(row["unobserved_source_seconds"] for row in patients),
        "m6_window_end_to_receipt_seconds": distribution(score_delay),
        "negative_score_delays_clock_warning": negative_delay,
        "different_run_identity_receipts": stale,
        "invalid_messages": invalid,
        "repeated_m6_window_receipts": repeated_scores,
        "conflicting_m6_window_receipts": conflicting_scores,
        "http_response_ms": {key: distribution(values) for key, values in probes.items()},
        "http_non_200_or_error": dict(failures),
        "resource_samples": len(resources),
        "resource_scope": "Raw CPU ticks/RSS in probes.jsonl; Windows resource checks NOT RUN",
        "event_sources": [{"filename": p.name, "sha256": digest(p)} for p in event_files],
        "limitations": [
            "Unobserved seconds may reflect capture loss, producer silence or rejection; "
            "not inferred packet loss.",
            "Repeated receipts are not necessarily repeated clinical effects.",
            "M6 path names are literal runtime values; unavailable is not stable.",
            "Score delay is not fault detection delay; HTTP time is not UI latency.",
            "Correlate owner source/DB/outbox/WS/UI evidence for actual scenario targets.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--events", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = fresh_output(args.output)
        result = summarize(args.observer, args.events)
        write_json(output / "metrics.json", result)
        print(json.dumps(result, indent=2))
        raise SystemExit(
            0 if result["status"] == "PASS" else 2 if result["status"] == "FAIL" else 3
        )
    except (ValueError, OSError, KeyError, TypeError):
        print("PHASE6 METRICS FAILED; verify retained capture and producer event files")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
