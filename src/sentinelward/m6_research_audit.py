"""Post-freeze uncertainty and integrity checks; never fits or selects a model."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path
from statistics import fmean
from typing import Any

from sentinelward.m6_cli import save_new
from sentinelward.m6_realdata import checksum


def incremental_detections(records: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Attribute only additional predictions, never already-positive reference windows."""

    def positive(record: dict[str, Any]) -> bool:
        extra = record["score"]["extra"]
        return (
            extra["inputs_sufficient"] is True
            and extra["drift_candidate"] is True
            and extra["emergency_compatible"] is False
            and record["score"]["score"] >= threshold
        )

    reference = {
        (row["patient_id"], row["score"]["window_start"]): row
        for row in records
        if row["variant"] == "reference"
    }
    results: dict[str, Any] = {}
    for row in records:
        if row["variant"] in {"reference", "coupled_low_pressure_control"}:
            continue
        result = results.setdefault(row["variant"], {"new_prediction_windows": 0, "delays_ms": {}})
        if (
            row["event_active"]
            and positive(row)
            and not positive(reference[(row["patient_id"], row["score"]["window_start"])])
        ):
            result["new_prediction_windows"] += 1
            delay = row["score"]["window_start"] + 10_000 - row["onset_ms"]
            delays = result["delays_ms"]
            delays[row["patient_id"]] = min(delay, delays.get(row["patient_id"], delay))
    for result in results.values():
        result["subjects_with_additional_prediction"] = len(result["delays_ms"])
        result["interpretation"] = "paired injection response; not clinically confirmed detection"
    return results


def paired_uncertainty(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for row in predictions:
        target = row["target_map"]
        groups.setdefault(row["patient_id"], []).append(
            (abs(row["old_ridge_prediction"] - target), abs(row["selected_prediction"] - target))
        )
    if not groups:
        raise ValueError("uncertainty requires paired held-out predictions")
    patients = sorted(groups)
    differences = {
        patient: fmean(old - new for old, new in groups[patient]) for patient in patients
    }
    rng = random.Random(20261009)
    bootstrap = sorted(
        fmean(differences[patient] for patient in rng.choices(patients, k=len(patients)))
        for _ in range(2000)
    )
    return {
        "unit": "independent subject; overlapping windows are not independent samples",
        "method": "paired patient-macro percentile bootstrap; 2000 draws, seed 20261009",
        "subjects": len(patients),
        "patient_mae_reduction_mmhg": differences,
        "macro_mae_reduction_mmhg": fmean(differences.values()),
        "bootstrap_95_percent_interval_mmhg": [bootstrap[49], bootstrap[1949]],
        "limitation": (
            "Very small cohort; interval does not establish clinical safety or generalization"
        ),
    }


def audit(root: Path, experiment: Path, output: Path) -> dict[str, Any]:
    report = json.loads((experiment / "report.json").read_text(encoding="utf-8"))
    if checksum(experiment / "selected-model.json") != report["regression"]["model_sha256"]:
        raise ValueError("frozen model integrity mismatch")
    predictions = json.loads((experiment / "heldout-predictions.json").read_text(encoding="utf-8"))
    if {row["patient_id"] for row in predictions} - set(report["split"]["test"]):
        raise ValueError("predictions contain non-test subjects")
    count = total_bytes = 0
    for receipt_path in root.rglob("*.receipt.json"):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        data_path = receipt_path.with_suffix("").with_suffix(".csv")
        if checksum(data_path) != receipt["sha256"] or data_path.stat().st_size != receipt["bytes"]:
            raise ValueError("dataset receipt mismatch")
        count += 1
        total_bytes += receipt["bytes"]
    if count == 0:
        raise ValueError("no dataset receipts verified")
    original = json.loads((experiment / "plan.json").read_text(encoding="utf-8"))
    for name, expected in original["source_hashes"].items():
        if checksum(experiment / "execution-source" / name) != expected:
            raise ValueError("original execution source integrity mismatch")
    resume_plan = experiment / "resume-plan.json"
    if resume_plan.exists():
        resumed = json.loads(resume_plan.read_text(encoding="utf-8"))
        resumed_folder = experiment / "resumed-execution-source"
        resumed_folder.mkdir(exist_ok=True)
        for name, expected in resumed["resumed_source_hashes"].items():
            source = Path(__file__).parent / name
            destination = resumed_folder / name
            if destination.exists():
                if checksum(destination) != expected:
                    raise ValueError("resumed execution source integrity mismatch")
            else:
                if checksum(source) != expected:
                    raise ValueError(
                        "resumed source changed before snapshot; cannot attest provenance"
                    )
                shutil.copyfile(source, destination)
    waveform_errors: list[float] = []
    score_records: list[dict[str, Any]] = []
    for patient in report["split"]["test"]:
        rows = json.loads((experiment / f"{patient}-features.json").read_text(encoding="utf-8"))
        waveform_errors.extend(abs(row["waveform_map"] - row["target_map"]) for row in rows)
        with (experiment / f"{patient}-scores.jsonl").open(encoding="utf-8") as stream:
            score_records.extend(json.loads(line) for line in stream)
    facts = {
        "report_sha256": checksum(experiment / "report.json"),
        "predictions_sha256": checksum(experiment / "heldout-predictions.json"),
        "frozen_model_sha256": report["regression"]["model_sha256"],
        "dataset_receipts_verified": count,
        "dataset_bytes_verified": total_bytes,
        "uncertainty": paired_uncertainty(predictions),
        "incremental_injection_responses": incremental_detections(
            score_records, original["drift_threshold"]
        ),
        "waveform_map_comparator_mae_mmhg": fmean(waveform_errors),
        "waveform_comparator_uses_current_arterial_pressure": True,
        "selected_physiology_model_does_not_use_current_arterial_pressure": True,
        "model_retrained_or_threshold_retuned": False,
        "original_and_resumed_execution_source_hashes_verified": True,
        "audit_source_sha256": checksum(Path(__file__)),
        "clinical_deployment_allowed": False,
    }
    save_new(output, facts)
    return facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    facts = audit(args.root, args.experiment, args.output)
    print(f"M6 AUDIT | {facts['dataset_receipts_verified']} receipts verified | RESEARCH ONLY")


if __name__ == "__main__":
    main()
