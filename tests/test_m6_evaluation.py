from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelward.cli import main
from sentinelward.contracts import ScoreMessage
from sentinelward.m6 import MODEL_VERSION, M6Config, feature_config_id
from sentinelward.m6_evaluation import (
    CalibrationArtifact,
    LabelledWindow,
    SplitManifest,
    calibrate,
    evaluate,
)


def split() -> SplitManifest:
    return SplitManifest(
        dataset_id="unit-fixtures",
        source="synthetic",
        train=["train"],
        validation=["validation"],
        test=["test"],
    )


def records(patient: str) -> list[LabelledWindow]:
    results = []
    for index, truth in enumerate(("stable", "drift", "hypotension")):
        score = ScoreMessage(
            v=1,
            type="score",
            bed_id="B01",
            model="M6",
            model_version=MODEL_VERSION,
            window_start=index * 5000,
            window_s=10,
            score=0.8 if truth == "drift" else 0.1,
            label="drift" if truth == "drift" else "stable",
            reason="Test evidence",
            extra={
                "inputs_sufficient": True,
                "drift_candidate": truth == "drift",
                "emergency_compatible": truth == "hypotension",
                "feature_config_id": feature_config_id(M6Config()),
                "cause_hint": "uncertain",
                "gap_mmhg": 15 if truth == "drift" else 0,
            },
        )
        results.append(
            LabelledWindow(
                patient_id=patient,
                event_id=f"event-{index}",
                truth=truth,
                onset_ms=5000 if truth == "drift" else None,
                score=score,
            )
        )
    return results


def test_disjoint_patient_splits_and_validation_only_threshold_selection() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        SplitManifest.model_validate(split().model_dump() | {"test": ["validation"]})
    with pytest.raises(ValueError, match="outside"):
        calibrate(records("test"), split())
    artifact = calibrate(records("validation"), split())
    assert artifact.config.evidence_threshold == 0.8
    assert CalibrationArtifact.model_validate_json(artifact.model_dump_json()) == artifact
    with pytest.raises(ValueError, match="integrity"):
        CalibrationArtifact.model_validate(artifact.model_dump() | {"validation_windows": 42})


def test_frozen_evaluation_reports_denominators_and_keeps_real_gate_pending() -> None:
    report = evaluate(records("test"), calibrate(records("validation"), split()))
    assert report["hypotension_false_drift"] == 0
    assert report["hypotension_windows"] == 1
    assert report["hypotension_patients"] == 1
    assert report["clinical_gate"] == "pending"
    assert report["detection_delay_ms"] == [10_000]
    assert report["drift_sensitivity"] == 1.0
    assert report["zero_failure_patient_upper95"] == pytest.approx(0.95)


def test_duplicates_configuration_mismatch_and_empty_safety_set_are_rejected_or_pending() -> None:
    artifact = calibrate(records("validation"), split())
    duplicate = records("test")
    with pytest.raises(ValueError, match="repeated"):
        evaluate(duplicate + duplicate, artifact)
    wrong = records("test")
    wrong[0].score.extra["feature_config_id"] = "wrong"
    with pytest.raises(ValueError, match="different M6 configuration"):
        evaluate(wrong, artifact)
    report = evaluate(records("test")[:2], artifact)
    assert report["clinical_gate"] == "pending" and report["hypotension_windows"] == 0
    with pytest.raises(ValueError, match="validation requires"):
        calibrate(records("validation")[:2], split())


def test_cli_evaluation_records_once_and_errors_are_short(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = calibrate(records("validation"), split())
    artifact_path = tmp_path / "artifact.json"
    record_path = tmp_path / "test.jsonl"
    report_path = tmp_path / "report.json"
    artifact_path.write_text(artifact.model_dump_json(), encoding="utf-8")
    record_path.write_text(
        "\n".join(row.model_dump_json() for row in records("test")), encoding="utf-8"
    )
    main(
        [
            "m6",
            "evaluate",
            "--artifact",
            str(artifact_path),
            "--records",
            str(record_path),
            "--report",
            str(report_path),
        ]
    )
    assert json.loads(report_path.read_text())["hypotension_false_drift"] == 0
    assert len(capsys.readouterr().out.strip()) <= 160
    with pytest.raises(SystemExit) as error:
        main(
            [
                "m6",
                "evaluate",
                "--artifact",
                str(artifact_path),
                "--records",
                str(record_path),
                "--report",
                str(tmp_path / "other.json"),
            ]
        )
    assert error.value.code == 2
    output = capsys.readouterr().err.strip()
    assert "FAILED" in output and "already recorded" in output and len(output) <= 160
