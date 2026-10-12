from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelward.m6 import MODEL_VERSION
from tools import resume_m6_preflight as runner


def cohort(root: Path) -> None:
    root.mkdir()
    cases = []
    for number in range(1, 7):
        patient = f"vitaldb-subject-{number}"
        folder = root / f"case-{number}"
        folder.mkdir()
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "patient_id": patient,
                    "bed_id": "B01",
                    "context": {
                        "episode_id": f"test-{number}",
                        "device_id": "MON-01",
                        "start_ts": 0,
                    },
                    "tracks": {},
                    "duration_s": 10,
                }
            ),
            encoding="utf-8",
        )
        cases.append({"case_id": str(number), "patient_id": patient})
    (root / "selection.json").write_text(json.dumps({"count": 6, "cases": cases}), encoding="utf-8")


def test_interrupted_audit_reuses_completed_patients_and_never_overwrites_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, checkpoints, report = (
        tmp_path / "cohort",
        tmp_path / "checkpoints",
        tmp_path / "report.json",
    )
    cohort(root)
    calls = []
    fail = True

    def inspect(*, manifest: Path) -> dict:
        nonlocal fail
        patient = json.loads(manifest.read_text())["patient_id"]
        calls.append(patient)
        if patient.endswith("-3") and fail:
            fail = False
            raise RuntimeError("controlled interruption")
        plan = json.loads((checkpoints / "plan.json").read_text())
        return {
            "model_version": MODEL_VERSION,
            "source_hashes": plan["source_hashes"],
            "patients": 1,
            "baseline_ready_patients": 0,
            "cases": [{"patient_id": patient, "baseline_ready": False}],
        }

    monkeypatch.setattr(runner, "preflight", inspect)
    with pytest.raises(RuntimeError, match="interruption"):
        runner.resume_preflight(root, checkpoints, report)
    assert len(list(checkpoints.glob("vitaldb-subject-*.json"))) == 2 and not report.exists()
    result = runner.resume_preflight(root, checkpoints, report)
    assert result["patients"] == 6 and calls.count("vitaldb-subject-1") == 1
    assert calls.count("vitaldb-subject-3") == 2
    before = report.read_bytes()
    runner.resume_preflight(root, checkpoints, report)
    assert report.read_bytes() == before and len(calls) == 7


def test_resume_rejects_changed_cached_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, checkpoints, report = (
        tmp_path / "cohort",
        tmp_path / "checkpoints",
        tmp_path / "report.json",
    )
    cohort(root)

    def inspect(*, manifest: Path) -> dict:
        patient = json.loads(manifest.read_text())["patient_id"]
        plan = json.loads((checkpoints / "plan.json").read_text())
        return {
            "model_version": MODEL_VERSION,
            "source_hashes": plan["source_hashes"],
            "cases": [{"patient_id": patient, "baseline_ready": False}],
        }

    monkeypatch.setattr(runner, "preflight", inspect)
    runner.resume_preflight(root, checkpoints, report)
    cache = checkpoints / "vitaldb-subject-1.json"
    payload = json.loads(cache.read_text())
    payload["preflight"]["cases"][0]["baseline_ready"] = True
    cache.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        runner.resume_preflight(root, checkpoints, report)
