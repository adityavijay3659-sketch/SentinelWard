"""Read-only longitudinal dataset preflight; never trains or certifies clinical readiness."""

from __future__ import annotations

import importlib.metadata
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sentinelward.m6 import MODEL_VERSION, M6Config, M6State, step
from sentinelward.m6_realdata import checksum, selection_cases
from sentinelward.m6_replay import ReplayManifest, replay_vitaldb


def inspect_case(path: Path) -> dict[str, Any]:
    manifest = ReplayManifest.model_validate_json(path.read_bytes())
    folder = path.parent.resolve()
    receipts = absent_receipts = 0
    for name in manifest.tracks.values():
        track = (folder / name).resolve()
        if not track.is_relative_to(folder):
            raise ValueError("track path must stay within the case directory")
        receipt_path = track.with_suffix(".receipt.json")
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                checksum(track) != receipt["sha256"]
                or track.stat().st_size != receipt["bytes"]
                or receipt["duration_s"] != manifest.duration_s
            ):
                raise ValueError("dataset receipt integrity or duration mismatch")
            receipts += 1
        else:
            if not track.is_file():
                raise FileNotFoundError("manifest track unavailable")
            absent_receipts += 1
    state = M6State(context=manifest.context, config=M6Config())
    labels: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    available: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    raw_features = eligible_run = longest_run = baseline_restarts = 0
    best_baseline_windows = 0
    cuff_timestamps: set[int] = set()
    first_baseline_ready: int | None = None
    for frame in replay_vitaldb(manifest, folder):
        if frame.nibp is not None:
            cuff_timestamps.add(frame.nibp.ts)
        score = step(state, frame)
        if score is None:
            continue
        raw_features += int(score.extra["input_availability"]["pressure_features"])
        labels[score.label] += 1
        blockers.update(score.extra["blocking_inputs"])
        available.update(
            name for name, present in score.extra["input_availability"].items() if present
        )
        paths[str(score.extra["assessment_path"])] += 1
        baseline_restarts += int(score.extra.get("baseline_restarted_after_gap") is True)
        best_baseline_windows = max(best_baseline_windows, len(state.baseline))
        # Baseline-eligible means the same guarded, synchronized evidence used
        # by the scorer. A reference-only window never satisfies this test.
        eligible = (
            score.label not in {"drift", "emergency_compatible"}
            and all(
                score.extra["input_availability"][key]
                for key in (
                    "complete_window",
                    "pressure_features",
                    "hr",
                    "ecg_ppg_timing",
                    "fresh_cuff",
                )
            )
            and abs(float(score.extra.get("gap_mmhg", 0))) < state.config.gap_mmhg
        )
        eligible_run = eligible_run + 1 if eligible else 0
        longest_run = max(longest_run, eligible_run)
        if first_baseline_ready is None and score.extra["baseline_ready"]:
            first_baseline_ready = score.window_start + 10_000
    windows = sum(labels.values())
    assessed = sum(paths[key] for key in ("cuff_gap_only", "baseline_combined"))
    return {
        "patient_id": manifest.patient_id,
        "manifest_sha256": checksum(path),
        "duration_s": manifest.duration_s,
        "windows": windows,
        "labels": dict(labels),
        "blocking_inputs": dict(blockers),
        "available_input_windows": dict(available),
        "assessment_paths": dict(paths),
        "drift_assessment_coverage": assessed / windows if windows else None,
        "usable_pressure_feature_windows": raw_features,
        "best_consecutive_baseline_windows": best_baseline_windows,
        "longest_eligible_run_windows": longest_run,
        "longest_eligible_run_span_ms": (longest_run - 1) * 5000 + 10_000 if longest_run else 0,
        "baseline_restarts": baseline_restarts,
        "baseline_required_windows": (state.config.baseline_seconds - 10) // 5 + 1,
        "first_baseline_ready_ts": first_baseline_ready,
        "baseline_ready": first_baseline_ready is not None,
        "distinct_observed_cuff_updates": len(cuff_timestamps),
        "cuff_time_provenance": "inferred_value_changes_not_verified_acquisition",
        "receipts_verified": receipts,
        "tracks_without_receipts": absent_receipts,
        "clinical_labels_reviewed": False,
        "clinical_deployment_allowed": False,
    }


def preflight(*, root: Path | None = None, manifest: Path | None = None) -> dict[str, Any]:
    source_hashes = {
        name: checksum(Path(__file__).with_name(name))
        for name in ("m6.py", "m6_replay.py", "m6_quality.py", "contracts.py")
    }
    if (root is None) == (manifest is None):
        raise ValueError("choose exactly one local cohort root or manifest")
    if root is not None:
        selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
        paths = [
            root / f"case-{case['case_id']}" / "manifest.json"
            for case in selection_cases(selection)
        ]
    else:
        assert manifest is not None
        paths = [manifest]
    cases = [inspect_case(path) for path in paths]
    if len({case["patient_id"] for case in cases}) != len(cases):
        raise ValueError("repeated patients cannot count as independent dataset coverage")
    versions = {}
    for package in ("sentinelward", "pydantic", "scikit-learn", "pytest", "psycopg"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    if any(
        checksum(Path(__file__).with_name(name)) != value for name, value in source_hashes.items()
    ):
        raise ValueError("preflight source changed during execution; report not saved")
    return {
        "model_version": MODEL_VERSION,
        "python_version": sys.version.split()[0],
        "installed_packages": versions,
        "source_hashes": source_hashes,
        "patients": len(cases),
        "baseline_ready_patients": sum(case["baseline_ready"] for case in cases),
        "cases": cases,
        "clinical_gate": "pending_reviewed_labels_verified_cuff_times_and_external_integration",
        "clinical_deployment_allowed": False,
        "purpose": "coverage diagnosis; unassessed windows and missing patients are not passes",
    }
