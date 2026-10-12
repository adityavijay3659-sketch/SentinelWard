"""Paired diagnostic replay on previously inspected patients; no fitting or tuning."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from sentinelward.m6 import MODEL_VERSION, M6Config
from sentinelward.m6_cli import save_new
from sentinelward.m6_forest import ForestArtifact, regression_metrics
from sentinelward.m6_realdata import checksum, selection_cases
from sentinelward.m6_revalidation import case_run, drift_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old_report = json.loads((args.experiment / "report.json").read_text(encoding="utf-8"))
    frozen_path = args.experiment / "selected-model.json"
    frozen_hash = checksum(frozen_path)
    if frozen_hash != old_report["regression"]["model_sha256"]:
        raise ValueError("historical frozen model integrity mismatch")
    model = ForestArtifact.model_validate_json(frozen_path.read_bytes())
    cases = selection_cases(json.loads((args.root / "selection.json").read_text(encoding="utf-8")))
    subjects = set(old_report["split"]["test"])
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "src" / "sentinelward"
    snapshot = args.output / "source"
    shutil.copytree(source, snapshot, ignore=shutil.ignore_patterns("__pycache__"))
    hashes = {path.name: checksum(path) for path in source.glob("*.py")}
    save_new(
        args.output / "plan.json",
        {
            "model_version": MODEL_VERSION,
            "source_hashes": hashes,
            "subjects": sorted(subjects),
            "threshold": M6Config().evidence_threshold,
            "model_sha256": frozen_hash,
            "historical_report_sha256": checksum(args.experiment / "report.json"),
            "selection_sha256": checksum(args.root / "selection.json"),
            "purpose": "paired repair diagnosis; these patients were already inspected",
            "model_fitting_or_threshold_tuning_allowed": False,
            "fresh_heldout_accuracy_claim_allowed": False,
        },
    )
    old_records = []
    new_records = []
    features = []
    qualities = []
    transitions: Counter[str] = Counter()
    urgent_downgrades = []
    for case in cases:
        patient = case["patient_id"]
        if patient not in subjects:
            continue
        rows, records, quality = case_run(args.root / f"case-{case['case_id']}", args.output)
        old_rows = json.loads(
            (args.experiment / f"{patient}-features.json").read_text(encoding="utf-8")
        )
        if rows != old_rows:
            raise ValueError("repair changed historical regression features or target alignment")
        with (args.experiment / f"{patient}-scores.jsonl").open(encoding="utf-8") as stream:
            old = [json.loads(line) for line in stream]
        old_index = {(r["variant"], r["score"]["window_start"]): r for r in old}
        new_index = {(r["variant"], r["score"]["window_start"]): r for r in records}
        if (
            len(old_index) != len(old)
            or len(new_index) != len(records)
            or old_index.keys() != new_index.keys()
        ):
            raise ValueError("paired replay has duplicated or mismatched windows")
        for key, record in new_index.items():
            transitions[
                f"{key[0]}:{old_index[key]['score']['label']}->{record['score']['label']}"
            ] += 1
            if (
                old_index[key]["score"]["label"] == "emergency_compatible"
                and record["score"]["label"] != "emergency_compatible"
            ):
                urgent_downgrades.append(
                    {"patient_id": patient, "variant": key[0], "window_start": key[1]}
                )
        old_records.extend(old)
        new_records.extend(records)
        features.extend(rows)
        qualities.append(quality)
        print(
            f"M6 REPAIR REPLAY | {len(qualities)}/{len(subjects)} patients | "
            f"urgent downgrades {len(urgent_downgrades)} | RESEARCH ONLY",
            flush=True,
        )
    if {quality["patient_id"] for quality in qualities} != subjects:
        raise ValueError("paired replay missed a historical patient")
    if checksum(frozen_path) != frozen_hash or any(
        checksum(source / name) != value for name, value in hashes.items()
    ):
        raise ValueError("model or execution source changed during repair replay")
    report = {
        "model_version": MODEL_VERSION,
        "patients": len(subjects),
        "quality": qualities,
        "paired_label_transitions": dict(transitions),
        "urgent_downgrades": urgent_downgrades,
        "urgent_precedence_preserved": not urgent_downgrades,
        "before": drift_metrics(old_records, M6Config().evidence_threshold),
        "after": drift_metrics(new_records, M6Config().evidence_threshold),
        "unchanged_frozen_regression": regression_metrics(
            features, [model.predict(row["features"]) for row in features]
        ),
        "regression_feature_rows_exactly_unchanged": True,
        "model_sha256": frozen_hash,
        "model_retrained_or_threshold_retuned": False,
        "fresh_heldout_accuracy_claim_allowed": False,
        "clinical_deployment_allowed": False,
        "clinical_gate": "pending_reviewed_labels_and_verified_cuff_acquisition",
    }
    save_new(args.output / "report.json", report)
    if urgent_downgrades:
        raise ValueError("repair downgraded historical urgent windows; inspect paired report")
    print("M6 REPAIR REPLAY | COMPLETE | RESEARCH ONLY")


if __name__ == "__main__":
    main()
