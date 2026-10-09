from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelward.m6_realdata import checksum
from sentinelward.m6_research_audit import audit, incremental_detections, paired_uncertainty


def test_complete_audit_without_resume_verifies_data_and_rejects_corruption(tmp_path: Path) -> None:
    root = tmp_path / "data"
    experiment = tmp_path / "experiment"
    root.mkdir()
    experiment.mkdir()

    def save(path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    track = root / "track.csv"
    track.write_text("Time,Value\n0,80\n", encoding="utf-8")
    save(root / "track.receipt.json", {"sha256": checksum(track), "bytes": track.stat().st_size})
    model = experiment / "selected-model.json"
    save(model, {})
    save(
        experiment / "report.json",
        {
            "regression": {"model_sha256": checksum(model)},
            "split": {"test": ["p"]},
        },
    )
    save(
        experiment / "heldout-predictions.json",
        [
            {
                "patient_id": "p",
                "target_map": 80,
                "old_ridge_prediction": 85,
                "selected_prediction": 82,
            }
        ],
    )
    save(experiment / "p-features.json", [{"waveform_map": 81, "target_map": 80}])
    (experiment / "p-scores.jsonl").write_text("", encoding="utf-8")
    source = experiment / "execution-source"
    source.mkdir()
    (source / "m6.py").write_text("frozen source", encoding="utf-8")
    save(
        experiment / "plan.json",
        {
            "source_hashes": {"m6.py": checksum(source / "m6.py")},
            "drift_threshold": 0.6,
        },
    )
    result = audit(root, experiment, experiment / "audit.json")
    assert result["dataset_receipts_verified"] == 1
    assert result["waveform_map_comparator_mae_mmhg"] == 1
    assert result["clinical_deployment_allowed"] is False
    track.write_text("changed track", encoding="utf-8")
    with pytest.raises(ValueError, match="receipt mismatch"):
        audit(root, experiment, experiment / "corrupt-audit.json")


def test_only_additional_injection_response_counts_as_detection() -> None:
    def row(variant: str, start: int, positive: bool):
        return {
            "patient_id": "p",
            "variant": variant,
            "event_active": True,
            "onset_ms": 900_000,
            "score": {
                "window_start": start,
                "score": 0.8,
                "extra": {
                    "inputs_sufficient": True,
                    "drift_candidate": positive,
                    "emergency_compatible": False,
                },
            },
        }

    facts = incremental_detections(
        [
            row("reference", 900_000, True),
            row("offset_plus_15", 900_000, True),
            row("reference", 905_000, False),
            row("offset_plus_15", 905_000, True),
        ],
        0.6,
    )
    assert facts["offset_plus_15"]["new_prediction_windows"] == 1
    assert facts["offset_plus_15"]["delays_ms"] == {"p": 15_000}


def test_uncertainty_clusters_by_patient_not_overlapping_window_count() -> None:
    rows = [
        {
            "patient_id": patient,
            "target_map": 80,
            "old_ridge_prediction": 85,
            "selected_prediction": 82,
        }
        for patient in ("p1", "p2")
    ]
    result = paired_uncertainty(rows)
    assert result["subjects"] == 2
    assert result["macro_mae_reduction_mmhg"] == 3
    assert result["bootstrap_95_percent_interval_mmhg"] == [3, 3]
    assert paired_uncertainty(rows + [rows[0]] * 100) == result


def test_uncertainty_is_reproducible_and_keeps_regressions_visible() -> None:
    rows = [
        {
            "patient_id": "p1",
            "target_map": 80,
            "old_ridge_prediction": 81,
            "selected_prediction": 85,
        },
        {
            "patient_id": "p2",
            "target_map": 80,
            "old_ridge_prediction": 84,
            "selected_prediction": 80,
        },
    ]
    result = paired_uncertainty(rows)
    assert result == paired_uncertainty(rows)
    assert result["patient_mae_reduction_mmhg"] == {"p1": -4, "p2": 4}
    assert result["bootstrap_95_percent_interval_mmhg"] == [-4, 4]
    with pytest.raises(ValueError, match="paired"):
        paired_uncertainty([])
