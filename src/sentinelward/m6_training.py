"""Offline real-recording MAP regression; NEVER substitutes for fresh cuff input.

Measured monitor MAP is a regression target, not reviewed clinical truth.
Weights are research artifacts and are deliberately not deployment artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from sentinelward.m6 import Features, extract_features
from sentinelward.m6_cli import save_new
from sentinelward.m6_realdata import checksum, selection_cases
from sentinelward.m6_replay import ReplayManifest, read_track, replay_vitaldb


class RegressionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str = "offline_monitor_map_regression_not_runtime_calibration"
    centres: list[FiniteFloat] = Field(min_length=3, max_length=3)
    scales: list[FiniteFloat] = Field(min_length=3, max_length=3)
    coefficients: list[FiniteFloat] = Field(min_length=3, max_length=3)
    intercept: FiniteFloat
    ridge: FiniteFloat = Field(gt=0)
    train_subjects: list[str]
    research_only: bool = True

    def predict(self, features: list[float]) -> float:
        return self.intercept + sum(
            coef * (value - centre) / scale
            for value, centre, scale, coef in zip(
                features, self.centres, self.scales, self.coefficients, strict=True
            )
        )


def vector(features: Features) -> list[float]:
    assert features.hr is not None and features.pat_ms is not None
    return [features.hr, features.pat_ms, features.amplitude]


def fit(rows: list[dict[str, Any]], patients: list[str], ridge: float) -> RegressionArtifact:
    if not rows or ridge <= 0 or {row["patient_id"] for row in rows} != set(patients):
        raise ValueError("training requires positive ridge and records for every training subject")
    if len(patients) != len(set(patients)):
        raise ValueError("repeated training subject")
    centres = [mean(row["features"][j] for row in rows) for j in range(3)]
    scales = [
        max(1.0, math.sqrt(mean((row["features"][j] - centres[j]) ** 2 for row in rows)))
        for j in range(3)
    ]
    intercept = mean(row["target_map"] for row in rows)
    x = [[(row["features"][j] - centres[j]) / scales[j] for j in range(3)] for row in rows]
    y = [row["target_map"] - intercept for row in rows]
    matrix = [
        [sum(row[i] * row[j] for row in x) + (ridge if i == j else 0.0) for j in range(3)]
        + [sum(row[i] * target for row, target in zip(x, y, strict=True))]
        for i in range(3)
    ]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda i: abs(matrix[i][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        divisor = matrix[col][col]
        matrix[col] = [value / divisor for value in matrix[col]]
        for i in range(3):
            if i != col:
                factor = matrix[i][col]
                matrix[i] = [a - factor * b for a, b in zip(matrix[i], matrix[col], strict=True)]
    return RegressionArtifact(
        centres=centres,
        scales=scales,
        coefficients=[matrix[j][3] for j in range(3)],
        intercept=intercept,
        ridge=ridge,
        train_subjects=patients,
    )


def assess(rows: list[dict[str, Any]], model: RegressionArtifact) -> dict[str, Any]:
    if not rows:
        return {"windows": 0, "mae_mmhg": None, "rmse_mmhg": None}
    errors = [model.predict(row["features"]) - row["target_map"] for row in rows]
    baseline = [model.intercept - row["target_map"] for row in rows]
    waveform = [row["waveform_map"] - row["target_map"] for row in rows]
    patients = sorted({row["patient_id"] for row in rows})
    return {
        "windows": len(rows),
        "subjects": len(patients),
        "mae_mmhg": mean(abs(error) for error in errors),
        "rmse_mmhg": math.sqrt(mean(error**2 for error in errors)),
        "mean_bias_mmhg": mean(errors),
        "training_mean_baseline_mae_mmhg": mean(abs(error) for error in baseline),
        "arterial_waveform_mean_mae_mmhg": mean(abs(error) for error in waveform),
        "patient_macro_mae_mmhg": mean(
            mean(
                abs(error)
                for row, error in zip(rows, errors, strict=True)
                if row["patient_id"] == patient
            )
            for patient in patients
        ),
    }


def extract_case(folder: Path, out: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = ReplayManifest.model_validate_json((folder / "manifest.json").read_bytes())
    target = read_track(
        folder / manifest.tracks["Solar8000/ART_MBP"],
        duration_s=manifest.duration_s,
        waveform=False,
    )
    frames = []
    rows = []
    total = unusable = target_missing = low_pressure_candidates = 0
    for frame in replay_vitaldb(manifest, folder):
        frames.append(frame)
        frames = frames[-10:]
        if len(frames) != 10 or (frame.ts + 1000) % 5000:
            continue
        total += 1
        features = extract_features(frames)
        if features is None or features.hr is None or features.pat_ms is None:
            unusable += 1
            continue
        measurement = target.recent((frame.ts - manifest.context.start_ts) / 1000, 5)
        if measurement is None or not 20 <= measurement[1] <= 200:
            target_missing += 1
            continue
        low_pressure_candidates += int(measurement[1] <= 65)
        rows.append(
            {
                "patient_id": manifest.patient_id,
                "window_start": frame.ts - 9000,
                "features": vector(features),
                "target_map": measurement[1],
                "target_ts": measurement[0],
                "waveform_map": features.map,
            }
        )
    save_new(out / f"{manifest.patient_id}-features.json", rows)
    return rows, {
        "patient_id": manifest.patient_id,
        "aligned_windows": total,
        "usable_regression_windows": len(rows),
        "unusable_features": unusable,
        "target_unusable_or_missing": target_missing,
        "low_monitor_map_candidate_windows": low_pressure_candidates,
        "clinical_labels_reviewed": False,
        "duplicate_target_samples": target.duplicate_samples,
        "conflicting_target_samples": target.conflicting_duplicates,
    }


def run(root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    cases = selection_cases(selection)
    size = len(cases) // 3
    split = {
        name: [case["patient_id"] for case in cases[i * size : (i + 1) * size]]
        for i, name in enumerate(("train", "validation", "test"))
    }
    candidates = [0.1, 1.0, 10.0, 100.0]
    save_new(
        out / "plan.json",
        {
            "split": split,
            "ridge_candidates": candidates,
            "hypothesis": (
                "HR/timing/amplitude ridge predicts recorded monitor MAP "
                "better than training-mean baseline"
            ),
            "acceptance": (
                "Held-out MAE improves on training-mean baseline; clinical safety not inferred"
            ),
            "target": "Observed Solar8000/ART_MBP at or before window end; max age 5 seconds",
            "selection_sha256": checksum(root / "selection.json"),
            "source_hashes": {
                name: checksum(Path(__file__).parent / name)
                for name in ("m6.py", "m6_replay.py", "m6_training.py")
            },
            "reference_channels": ["HR", "ECG/PPG timing proxy", "arterial pulse amplitude"],
            "research_only": True,
            "deployment_eligible": False,
            "clinical_labels_reviewed": False,
        },
    )
    data: dict[str, list[dict[str, Any]]] = {}
    quality = []
    model: RegressionArtifact | None = None
    frozen_hash: str | None = None
    tuning = []
    for phase in ("train", "validation", "test"):
        if phase == "test":
            assert model is not None and frozen_hash is not None
            assert checksum(out / "model.json") == frozen_hash
        data[phase] = []
        for case in cases:
            if case["patient_id"] in split[phase]:
                rows, facts = extract_case(root / f"case-{case['case_id']}", out)
                data[phase].extend(rows)
                facts["split"] = phase
                quality.append(facts)
                print(
                    f"M6 REGRESSION | {phase.upper()} | case {case['case_id']} | "
                    f"{len(rows)} usable windows",
                    flush=True,
                )
        if phase == "validation":
            if {row["patient_id"] for row in data[phase]} != set(split[phase]):
                raise ValueError("some validation subjects have no usable regression windows")
            choices = []
            for ridge in candidates:
                fitted = fit(data["train"], split["train"], ridge)
                validation = assess(data[phase], fitted)
                tuning.append({"ridge": ridge, "validation": validation})
                choices.append((validation["mae_mmhg"], ridge, fitted))
            model = min(choices, key=lambda choice: (choice[0], choice[1]))[2]
            save_new(out / "model.json", model.model_dump(mode="json"))
            frozen_hash = checksum(out / "model.json")
            save_new(
                out / "validation.json", {"candidates": tuning, "frozen_model_sha256": frozen_hash}
            )
    assert model is not None
    test = assess(data["test"], model)
    represented = {row["patient_id"] for row in data["test"]}
    complete = represented == set(split["test"])
    passed = (
        complete
        and test["mae_mmhg"] is not None
        and test["mae_mmhg"] < test["training_mean_baseline_mae_mmhg"]
    )
    report = {
        "source": "VitalDB real surgical recordings",
        "split": split,
        "model_sha256": frozen_hash,
        "selected_ridge": model.ridge,
        "train": assess(data["train"], model),
        "validation": assess(data["validation"], model),
        "heldout": test,
        "quality": quality,
        "heldout_subject_coverage_complete": complete,
        "research_hypothesis_passed": passed,
        "train_window_count": len(data["train"]),
        "heldout_rows_sha256": hashlib.sha256(
            json.dumps(data["test"], sort_keys=True).encode()
        ).hexdigest(),
        "clinical_gate": "pending",
        "deployment_eligible": False,
        "limitations": [
            "Monitor MAP is an observed device target, not adjudicated clinical ground truth",
            (
                "Arterial amplitude itself depends on pressure: this is a physiology regression, "
                "not an independent cuff substitute"
            ),
            "No drift/tampering clinical labels and no clinical sensitivity/specificity claim",
            "No runtime model replacement; fresh cuff and emergency guards are unchanged",
        ],
    }
    save_new(out / "report.json", report)
    print(f"M6 REGRESSION | HELD OUT | MAE {test['mae_mmhg']:.2f} mmHg | RESEARCH ONLY", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.output)


if __name__ == "__main__":
    main()
