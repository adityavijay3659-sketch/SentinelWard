from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelward.m6_demo import synthetic_frame
from tools.phase6_acceptance import digest, write_json
from tools.phase6_metrics import distribution, summarize
from tools.phase6_observe import observation


def test_metric_empty_denominators_and_nearest_rank_percentiles() -> None:
    assert distribution([]) == {"n": 0, "p50": None, "p95": None, "max": None}
    assert distribution([1, 2, 3, 4])["p95"] == 4


def test_metrics_keep_missing_unassessed_and_duplicate_windows_explicit(tmp_path: Path) -> None:
    start = 2_000_000
    frame = synthetic_frame(0).model_dump(mode="json") | {"ts": start, "nibp": None}
    vitals = observation("ward/bed/B01/vitals", json.dumps(frame).encode(), start, "run_A")
    score = {
        "v": 1,
        "type": "score",
        "bed_id": "B01",
        "model": "M6",
        "model_version": "m6-research-0.3.4",
        "window_start": start,
        "window_s": 10,
        "label": "insufficient_data",
        "score": 0.0,
        "reason": "Unavailable",
        "extra": {"demo_run_id": "run_A", "assessment_path": "unavailable"},
    }
    row = observation("ward/bed/B01/score/M6", json.dumps(score).encode(), start + 11000, "run_A")
    (tmp_path / "wire.jsonl").write_text(
        "\n".join(json.dumps(r) for r in [vitals, row, row]) + "\n"
    )
    (tmp_path / "probes.jsonl").write_text('{"id":"live","elapsed_ms":2.5,"status_code":200}\n')
    write_json(
        tmp_path / "observation-summary.json",
        {
            "schema_version": 1,
            "status": "PASS",
            "run_id": "run_A",
            "capture_start_ts": start - 100,
            "capture_end_ts": start + 1200000,
            "files": {name: digest(tmp_path / name) for name in ["wire.jsonl", "probes.jsonl"]},
        },
    )
    events = tmp_path / "events.jsonl"
    rows = [
        {
            "run_id": "run_A",
            "t_s": t,
            "ts": start + t * 1000,
            "event": event,
            "bed_id": None,
            "detail": {},
        }
        for t, event in [(0, "run_start"), (1200, "run_end")]
    ]
    events.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    result = summarize(tmp_path, [events])
    assert result["status"] == "PASS"  # capture integrity, explicitly not system acceptance
    assert result["expected_vitals_frames"] == 11790
    assert result["unobserved_source_seconds"] == 11789
    assert result["repeated_m6_window_receipts"] == 1
    assert result["m6_window_end_to_receipt_seconds"]["n"] == 1
    bed = result["patients"][0]
    assert bed["m6_counts"] == {"label:insufficient_data": 1, "path:unavailable": 1}
    assert bed["unobserved_source_seconds"] == 1199
    events.write_text(json.dumps(rows[1]) + "\n")
    assert summarize(tmp_path, [events])["status"] == "BLOCKED"
    (tmp_path / "wire.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        summarize(tmp_path, [events])
