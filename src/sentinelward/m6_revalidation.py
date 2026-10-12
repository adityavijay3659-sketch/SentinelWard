"""M6-only, new-subject research evaluation. No inferred clinical diagnoses."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import time
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any

from sentinelward.contracts import CuffReading, VitalsMessage
from sentinelward.m6 import MODEL_VERSION, M6Config, M6State, step
from sentinelward.m6_cli import save_new
from sentinelward.m6_forest import ForestArtifact, fit_forest, regression_metrics
from sentinelward.m6_realdata import checksum, perturb, selection_cases
from sentinelward.m6_replay import ReplayManifest, read_track, replay_vitaldb
from sentinelward.m6_training import RegressionArtifact, fit
from sentinelward.presentation import wire_output_views

ONSET = 900_000
VARIANTS = (
    "reference",
    "offset_plus_15",
    "offset_minus_15",
    "ramp_plus_15",
    "ramp_30min_plus_15",
    "amplitude_attenuation",
    "coupled_low_pressure_control",
)


def modify(frame: VitalsMessage, variant: str, onset_ms: int = ONSET) -> VitalsMessage:
    if frame.ts < onset_ms:
        return frame
    if variant == "ramp_30min_plus_15" and frame.abp is not None:
        shift = min(15.0, 15 * (frame.ts - onset_ms) / 1_800_000)
        return frame.model_copy(update={"abp": [value + shift for value in frame.abp]})
    if variant == "coupled_low_pressure_control":
        cuff = CuffReading(sys=80, dia=40, map=55, ts=frame.nibp.ts) if frame.nibp else None
        abp = None
        if frame.abp is not None:
            centre = fmean(frame.abp)
            abp = [55 + 0.2 * (value - centre) for value in frame.abp]
        return frame.model_copy(update={"abp": abp, "nibp": cuff})
    return perturb(frame, variant, onset_ms)


def case_run(
    folder: Path, out: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = ReplayManifest.model_validate_json((folder / "manifest.json").read_bytes())
    target = read_track(
        folder / manifest.tracks["Solar8000/ART_MBP"],
        duration_s=manifest.duration_s,
        waveform=False,
    )
    states = {name: M6State(context=manifest.context, config=M6Config()) for name in VARIANTS}
    onset = manifest.context.start_ts + ONSET
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    timings = []
    examples: dict[str, Any] = {}
    with (out / f"{manifest.patient_id}-scores.jsonl").open("x", encoding="utf-8") as stream:
        for frame in replay_vitaldb(manifest, folder):
            for variant, state in states.items():
                before = time.perf_counter()
                score = step(state, modify(frame, variant, onset))
                elapsed = (time.perf_counter() - before) * 1000
                if score is None:
                    continue
                timings.append(elapsed)
                record = {
                    "patient_id": manifest.patient_id,
                    "variant": variant,
                    "event_active": score.window_start >= onset,
                    "onset_ms": onset,
                    "clinical_labels_reviewed": False,
                    "score": score.model_dump(mode="json"),
                }
                stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                records.append(record)
                if variant != "reference":
                    continue
                counts[score.label] += 1
                reasons[score.reason] += 1
                views = wire_output_views(score)
                examples.setdefault(
                    score.label, {"user": views.user, "team": views.team, "model": views.model}
                )
                features = score.extra.get("features", {})
                observation = target.recent((frame.ts - manifest.context.start_ts) / 1000, 5)
                if (
                    features.get("hr") is not None
                    and features.get("pat_ms") is not None
                    and observation is not None
                    and 20 <= observation[1] <= 200
                ):
                    rows.append(
                        {
                            "patient_id": manifest.patient_id,
                            "window_start": score.window_start,
                            "features": [features["hr"], features["pat_ms"], features["amplitude"]],
                            "waveform_map": features["map"],
                            "target_map": observation[1],
                            "target_ts": observation[0],
                        }
                    )
    save_new(out / f"{manifest.patient_id}-features.json", rows)
    ordered = sorted(timings)
    return (
        rows,
        records,
        {
            "patient_id": manifest.patient_id,
            "reference_windows": sum(counts.values()),
            "label_counts": dict(counts),
            "blocking_reasons": dict(reasons),
            "baseline_windows": len(states["reference"].baseline),
            "baseline_ready": len(states["reference"].baseline) >= 179,
            "available_cuff_gap_assessment_windows": sum(
                r["score"]["extra"]["assessment_path"] == "cuff_gap_only"
                for r in records
                if r["variant"] == "reference"
            ),
            "usable_map_target_windows": len(rows),
            "score_window_p95_ms": ordered[int(0.95 * (len(ordered) - 1))],
            "examples": examples,
        },
    )


def drift_metrics(records: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    reference = {
        (r["patient_id"], r["score"]["window_start"]): r
        for r in records
        if r["variant"] == "reference"
    }

    def positive(record: dict[str, Any]) -> bool:
        extra = record["score"]["extra"]
        return (
            extra["inputs_sufficient"] is True
            and extra["drift_candidate"] is True
            and extra["emergency_compatible"] is False
            and record["score"]["score"] >= threshold
        )

    result: dict[str, Any] = {}
    for variant in VARIANTS:
        selected = [r for r in records if r["variant"] == variant and r["event_active"]]
        if not selected:
            result[variant] = {"status": "not_evaluated", "reason": "no active windows"}
            continue
        hits = [r for r in selected if positive(r)]
        new_hits = [
            r
            for r in hits
            if not positive(reference[(r["patient_id"], r["score"]["window_start"])])
        ]
        subjects = sorted({r["patient_id"] for r in selected})
        reference_clear = [
            r
            for r in selected
            if not positive(reference[(r["patient_id"], r["score"]["window_start"])])
        ]
        attributable = (
            hits if variant in {"reference", "coupled_low_pressure_control"} else new_hits
        )
        delays = {
            patient: min(
                r["score"]["window_start"] + 10_000 - r.get("onset_ms", ONSET)
                for r in attributable
                if r["patient_id"] == patient
            )
            for patient in subjects
            if any(r["patient_id"] == patient for r in attributable)
        }
        sufficient = sum(r["score"]["extra"]["inputs_sufficient"] is True for r in selected)
        result[variant] = {
            "windows": len(selected),
            "subjects": len(subjects),
            "inputs_sufficient_windows": sufficient,
            "input_coverage": sufficient / len(selected),
            "drift_predictions": len(hits),
            "prediction_fraction_all_windows": len(hits) / len(selected),
            "incremental_predictions_over_paired_reference": len(new_hits),
            "paired_reference_nonpositive_windows": len(reference_clear),
            "incremental_prediction_fraction": len(new_hits) / len(reference_clear)
            if reference_clear
            else None,
            "subjects_with_drift_prediction": len(delays),
            "detection_delay_ms": delays,
            "delay_policy": "additional predictions over paired reference"
            if variant not in {"reference", "coupled_low_pressure_control"}
            else "raw predictions; no clinical detection claim",
            "urgent_windows": sum(r["score"]["label"] == "emergency_compatible" for r in selected),
            "interpretation": "controlled perturbation, not clinical sensitivity"
            if variant not in {"reference", "coupled_low_pressure_control"}
            else "unreviewed original recordings"
            if variant == "reference"
            else "synthetic guard control",
        }
    return result


def coverage(rows: list[dict[str, Any]], subjects: list[str]) -> dict[str, Any]:
    available = {row["patient_id"] for row in rows}
    return {
        "subjects_expected": len(subjects),
        "subjects_evaluable": len(available),
        "subjects_without_usable_targets": sorted(set(subjects) - available),
        "status": "complete" if available == set(subjects) else "incomplete",
        "metrics_scope": "usable windows only; missing subjects are not passes",
    }


def snapshot_sources(hashes: dict[str, str], source: Path, destination: Path) -> None:
    for name, expected in hashes.items():
        if checksum(source / name) != expected:
            raise ValueError("execution source changed after plan creation")
    destination.mkdir(exist_ok=True)
    for name, expected in hashes.items():
        target = destination / name
        if target.exists():
            if checksum(target) != expected:
                raise ValueError("existing execution snapshot integrity mismatch")
        else:
            shutil.copyfile(source / name, target)


def run(root: Path, previous: Path, out: Path, *, resume: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=resume)
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    cases = selection_cases(selection)
    size = len(cases) // 3
    split = {
        name: [case["patient_id"] for case in cases[i * size : (i + 1) * size]]
        for i, name in enumerate(("train", "validation", "test"))
    }
    prior_plan = json.loads((previous / "plan.json").read_text(encoding="utf-8"))
    retired = [patient for group in prior_plan["split"].values() for patient in group]
    if set(retired) & {case["patient_id"] for case in cases}:
        raise ValueError("new cohort overlaps a retired subject")
    prior = RegressionArtifact.model_validate_json((previous / "model.json").read_bytes())
    population_training = []
    for patient in retired:
        population_training.extend(
            json.loads((previous / f"{patient}-features.json").read_text(encoding="utf-8"))
        )
    plan: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "split": split,
        "retired_to_development_subjects": retired,
        "hypothesis": (
            "new nonlinear physiology regression improves paired held-out MAE over old ridge"
        ),
        "forest_candidates": [
            {"depth": 6, "leaf": 20},
            {"depth": 10, "leaf": 20},
            {"depth": 10, "leaf": 50},
        ],
        "ridge_candidates": [0.1, 1, 10, 100],
        "selection_metric": "validation patient-macro MAE",
        "selection_sha256": checksum(root / "selection.json"),
        "injection_onset_ms": ONSET,
        "drift_threshold": M6Config().evidence_threshold,
        "threshold_tuned": False,
        "clinical_labels_reviewed": False,
        "clinical_deployment_allowed": False,
        "source_hashes": {
            name: checksum(Path(__file__).parent / name)
            for name in (
                "m6.py",
                "m6_cohort.py",
                "m6_replay.py",
                "m6_forest.py",
                "m6_revalidation.py",
            )
        },
        "environment": {
            name: importlib.metadata.version(name) for name in ("numpy", "scikit-learn", "scipy")
        },
        "limitations": [
            "reference-availability screening narrows population",
            "old test retired to development; new test subjects untouched before freeze",
            "monitor targets and synthetic injections do not establish clinical readiness",
        ],
    }
    if resume:
        original_plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
        for key in ("split", "selection_sha256", "drift_threshold", "model_version"):
            if original_plan[key] != plan[key]:
                raise ValueError(f"resume plan mismatch: {key}")
        if (out / "selected-model.json").exists():
            raise ValueError("resume cannot refit a model after held-out evaluation began")
        save_new(
            out / "resume-plan.json",
            {
                "reason": "validation subject has no usable waveform; preserve as abstention",
                "coverage_policy": "report missing subjects; fit on available training/validation",
                "model_selection_unchanged": True,
                "heldout_evaluation_started": False,
                "original_plan_sha256": checksum(out / "plan.json"),
                "resumed_source_hashes": plan["source_hashes"],
            },
        )
    else:
        save_new(out / "plan.json", plan)
    snapshot_sources(
        plan["source_hashes"],
        Path(__file__).parent,
        out / ("resumed-execution-source" if resume else "execution-source"),
    )
    qualities = []
    data: dict[str, list[dict[str, Any]]] = {}
    scores: dict[str, list[dict[str, Any]]] = {}
    model: ForestArtifact | RegressionArtifact | None = None
    model_kind = ""
    frozen_hash = ""
    train_subjects = retired + split["train"]
    for phase in ("train", "validation", "test"):
        if phase == "test":
            assert model is not None and checksum(out / "selected-model.json") == frozen_hash
        data[phase] = []
        scores[phase] = []
        for case in cases:
            if case["patient_id"] not in split[phase]:
                continue
            folder = root / f"case-{case['case_id']}"
            deadline = time.monotonic() + 900
            while not (folder / "manifest.json").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("cohort download did not finish in bounded wait")
                time.sleep(5)
            quality_path = out / f"{case['patient_id']}-quality.json"
            if resume and quality_path.exists():
                quality = json.loads(quality_path.read_text(encoding="utf-8"))
                rows = json.loads(
                    (out / f"{case['patient_id']}-features.json").read_text(encoding="utf-8")
                )
                records = [
                    json.loads(line)
                    for line in (out / f"{case['patient_id']}-scores.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                if len(records) != quality["reference_windows"] * len(VARIANTS):
                    raise ValueError("cached replay is incomplete")
            else:
                rows, records, quality = case_run(folder, out)
                quality["split"] = phase
                save_new(quality_path, quality)
            data[phase].extend(rows)
            scores[phase].extend(records)
            quality["split"] = phase
            qualities.append(quality)
            print(
                f"M6 RECHECK | {phase.upper()} | baseline {quality['baseline_windows']}/179 | "
                f"gap-only windows {quality['available_cuff_gap_assessment_windows']}",
                flush=True,
            )
        if phase == "validation":
            if not data[phase]:
                raise ValueError("no evaluable validation targets; cannot select a model")
            training = population_training + data["train"]
            choices: list[tuple[float, str, ForestArtifact | RegressionArtifact]] = []
            results = []
            for ridge in (0.1, 1, 10, 100):
                fitted = fit(training, train_subjects, ridge)
                fact = regression_metrics(
                    data[phase], [fitted.predict(row["features"]) for row in data[phase]]
                )
                macro = fmean(fact["patient_mae_mmhg"].values())
                choices.append((macro, f"ridge-{ridge}", fitted))
                results.append({"candidate": f"ridge-{ridge}", "macro_mae": macro, "metrics": fact})
            for depth, leaf in ((6, 20), (10, 20), (10, 50)):
                fitted_forest = fit_forest(training, train_subjects, depth=depth, leaf=leaf)
                fact = regression_metrics(
                    data[phase], [fitted_forest.predict(row["features"]) for row in data[phase]]
                )
                macro = fmean(fact["patient_mae_mmhg"].values())
                choices.append((macro, f"forest-{depth}-{leaf}", fitted_forest))
                results.append(
                    {"candidate": f"forest-{depth}-{leaf}", "macro_mae": macro, "metrics": fact}
                )
            _, model_kind, model = min(choices, key=lambda choice: (choice[0], choice[1]))
            save_new(out / "selected-model.json", model.model_dump(mode="json"))
            frozen_hash = checksum(out / "selected-model.json")
            save_new(
                out / "validation.json",
                {
                    "candidates": results,
                    "selected": model_kind,
                    "model_sha256": frozen_hash,
                    "coverage": coverage(data[phase], split[phase]),
                    "old_ridge": regression_metrics(
                        data[phase], [prior.predict(row["features"]) for row in data[phase]]
                    ),
                },
            )
            print(f"M6 MODEL | FROZEN | {model_kind} | test subjects still sealed", flush=True)
    assert model is not None
    test_rows = data["test"]
    predicted = [model.predict(row["features"]) for row in test_rows]
    old_predicted = [prior.predict(row["features"]) for row in test_rows]
    if not test_rows:
        raise ValueError("no held-out targets; regression cannot be evaluated")
    new_fact = regression_metrics(test_rows, predicted)
    old_fact = regression_metrics(test_rows, old_predicted)
    predictions = [
        {
            "patient_id": row["patient_id"],
            "window_start": row["window_start"],
            "target_map": row["target_map"],
            "selected_prediction": new,
            "old_ridge_prediction": old,
        }
        for row, new, old in zip(test_rows, predicted, old_predicted, strict=True)
    ]
    save_new(out / "heldout-predictions.json", predictions)
    review = [
        {
            "patient_id": row["patient_id"],
            "window_start": row["window_start"],
            "source": "Solar8000/ART_MBP",
            "observed_map": row["target_map"],
            "status": "candidate_requires_clinical_adjudication",
        }
        for group in data.values()
        for row in group
        if row["target_map"] <= 65
    ]
    save_new(out / "clinical-review-candidates.json", review)
    report = {
        "model_version": MODEL_VERSION,
        "subjects": len(cases),
        "split": split,
        "case_runs_completed": len(qualities),
        "baseline_ready_subjects": sum(q["baseline_ready"] for q in qualities),
        "regression": {
            "coverage": {phase: coverage(data[phase], split[phase]) for phase in data},
            "selected": model_kind,
            "model_sha256": frozen_hash,
            "new": new_fact,
            "old_paired": old_fact,
            "paired_improvement_mmhg": old_fact["mae_mmhg"] - new_fact["mae_mmhg"],
            "improvement_observed": new_fact["mae_mmhg"] < old_fact["mae_mmhg"],
        },
        "heldout_drift": drift_metrics(scores["test"], M6Config().evidence_threshold),
        "validation_drift": drift_metrics(scores["validation"], M6Config().evidence_threshold),
        "quality": qualities,
        "clinical_gate": "pending_reviewed_labels_and_representative_validation",
        "clinical_review_candidate_windows": len(review),
        "runtime_research_only": True,
        "hypothesis_passed": new_fact["mae_mmhg"] < old_fact["mae_mmhg"],
        "no_assumption_of_clinically_stable_reference": True,
        "score_timings_exclude_database_and_network": True,
    }
    save_new(out / "report.json", report)
    print(
        f"M6 | REEVALUATED | MAE {new_fact['mae_mmhg']:.2f} "
        f"versus {old_fact['mae_mmhg']:.2f} mmHg | RESEARCH ONLY",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--previous-regression", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.root, args.previous_regression, args.output, resume=args.resume)


if __name__ == "__main__":
    main()
