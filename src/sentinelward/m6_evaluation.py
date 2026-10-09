"""Validation-only threshold selection and patient-separated frozen evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinelward.contracts import Identifier, ScoreMessage
from sentinelward.m6 import MODEL_VERSION, M6Config, feature_config_id


class SplitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: Identifier
    source: Literal["synthetic", "vitaldb"]
    labels_reviewed: bool = False
    train: list[Identifier] = Field(min_length=1)
    validation: list[Identifier] = Field(min_length=1)
    test: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def disjoint(self) -> SplitManifest:
        all_ids = self.train + self.validation + self.test
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("patient splits must be disjoint and contain no repeated IDs")
        return self


class LabelledWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    patient_id: Identifier
    event_id: Identifier
    onset_ms: int | None = Field(default=None, ge=0)
    truth: Literal["stable", "drift", "tampering", "hypotension"]
    score: ScoreMessage

    @model_validator(mode="after")
    def valid_m6(self) -> LabelledWindow:
        if (
            self.score.model != "M6"
            or self.score.window_s != 10
            or self.score.window_start % 5000
            or self.score.model_version != MODEL_VERSION
        ):
            raise ValueError("evaluation requires aligned current-version M6 scores")
        return self


class CalibrationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str
    model_version: Literal["m6-research-0.3.1"] = MODEL_VERSION
    split: SplitManifest
    config: M6Config
    validation_sha256: str
    validation_windows: int = Field(gt=0)
    selection: Literal["max_recall_zero_hypotension_fp_bounded_stable_fp"]
    stable_fp_limit: float = Field(ge=0, le=1)
    research_only: Literal[True] = True

    @model_validator(mode="after")
    def verified_hash(self) -> CalibrationArtifact:
        if self.artifact_id != artifact_hash(self.model_dump(mode="json", exclude={"artifact_id"})):
            raise ValueError("calibration artifact integrity check failed")
        return self


def artifact_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_labelled(path: Path) -> list[LabelledWindow]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                records.append(LabelledWindow.model_validate_json(line))
    return records


def validate_records(
    records: list[LabelledWindow], *, patients: Iterable[str], config: M6Config
) -> None:
    allowed = set(patients)
    seen = set()
    events: dict[tuple[str, str], tuple[str, int | None]] = {}
    for record in records:
        key = (record.patient_id, record.score.window_start)
        if record.patient_id not in allowed:
            raise ValueError("records include a patient outside the selected split")
        if key in seen:
            raise ValueError("repeated patient/window would bias evaluation")
        seen.add(key)
        event = (record.patient_id, record.event_id)
        fact = (record.truth, record.onset_ms)
        if event in events and events[event] != fact:
            raise ValueError("event truth/onset is inconsistent")
        events[event] = fact
        extra = record.score.extra
        if extra.get("feature_config_id") != feature_config_id(config):
            raise ValueError("record features were produced with a different M6 configuration")
        if not isinstance(extra.get("drift_candidate"), bool) or not isinstance(
            extra.get("inputs_sufficient"), bool
        ):
            raise ValueError("M6 evidence metadata is missing")


def predicted_drift(record: LabelledWindow, threshold: float) -> bool:
    extra = record.score.extra
    return (
        extra.get("inputs_sufficient") is True
        and extra.get("drift_candidate") is True
        and extra.get("emergency_compatible") is False
        and record.score.score >= threshold
    )


def calibrate(
    records: list[LabelledWindow],
    split: SplitManifest,
    config: M6Config | None = None,
    *,
    stable_fp_limit: float = 0.01,
) -> CalibrationArtifact:
    base = config or M6Config()
    validate_records(records, patients=split.validation, config=base)
    if {record.patient_id for record in records} != set(split.validation):
        raise ValueError("all validation patients must be represented")
    if not 0 <= stable_fp_limit <= 1:
        raise ValueError("stable false-positive limit must be in 0..1")
    if not {"stable", "drift", "hypotension"}.issubset({record.truth for record in records}):
        raise ValueError(
            "validation requires stable, injected-drift and reviewed hypotension labels"
        )
    candidates = sorted(
        {0.01, 1.0, *(record.score.score for record in records if record.score.score > 0)}
    )
    best: tuple[int, int, float] | None = None
    for threshold in candidates:
        tp = sum(
            predicted_drift(record, threshold)
            for record in records
            if record.truth in {"drift", "tampering"}
        )
        stable = [record for record in records if record.truth == "stable"]
        fp = sum(predicted_drift(record, threshold) for record in stable)
        unsafe = any(
            predicted_drift(record, threshold)
            for record in records
            if record.truth == "hypotension"
        )
        if unsafe or fp / len(stable) > stable_fp_limit:
            continue
        choice = (tp, -fp, threshold)  # deterministic tie break: higher threshold
        if best is None or choice > best:
            best = choice
    if best is None or best[0] == 0:
        raise ValueError("no useful threshold satisfies the validation safety constraints")
    values = {
        "model_version": MODEL_VERSION,
        "split": split.model_dump(mode="json"),
        "config": base.model_copy(
            update={"evidence_threshold": best[2], "calibration_id": None}
        ).model_dump(mode="json"),
        "validation_sha256": artifact_hash([record.model_dump(mode="json") for record in records]),
        "validation_windows": len(records),
        "selection": "max_recall_zero_hypotension_fp_bounded_stable_fp",
        "stable_fp_limit": stable_fp_limit,
        "research_only": True,
    }
    return CalibrationArtifact.model_validate({"artifact_id": artifact_hash(values), **values})


def evaluate(records: list[LabelledWindow], artifact: CalibrationArtifact) -> dict[str, object]:
    validate_records(records, patients=artifact.split.test, config=artifact.config)
    if {record.patient_id for record in records} != set(artifact.split.test):
        raise ValueError("all held-out test patients must be represented")
    threshold = artifact.config.evidence_threshold
    truth_counts = Counter(record.truth for record in records)
    tp = fp = fn = tn = unsafe = 0
    baseline_tp = baseline_fp = baseline_unsafe = 0
    cause_confusion: Counter[str] = Counter()
    delays: dict[tuple[str, str], int | None] = {}
    for record in records:
        positive = record.truth in {"drift", "tampering"}
        predicted = predicted_drift(record, threshold)
        tp += int(positive and predicted)
        fp += int(not positive and predicted)
        fn += int(positive and not predicted)
        tn += int(not positive and not predicted)
        unsafe += int(record.truth == "hypotension" and predicted)
        gap = record.score.extra.get("gap_mmhg")
        baseline_predicted = isinstance(gap, (int, float)) and abs(gap) >= artifact.config.gap_mmhg
        baseline_tp += int(positive and baseline_predicted)
        baseline_fp += int(not positive and baseline_predicted)
        baseline_unsafe += int(record.truth == "hypotension" and baseline_predicted)
        if positive:
            cause_confusion[
                f"{record.truth}->{record.score.extra.get('cause_hint', 'uncertain')}"
            ] += 1
            key = (record.patient_id, record.event_id)
            delays.setdefault(key, None)
            if predicted and record.onset_ms is not None:
                end = record.score.window_start + record.score.window_s * 1000
                delay = end - record.onset_ms
                previous_delay = delays[key]
                if delay >= 0 and (previous_delay is None or delay < previous_delay):
                    delays[key] = delay
    hypo_patients = {record.patient_id for record in records if record.truth == "hypotension"}
    measured = [delay for delay in delays.values() if delay is not None]
    real_gate = (
        artifact.split.source == "vitaldb"
        and artifact.split.labels_reviewed
        and truth_counts["hypotension"] > 0
        and unsafe == 0
    )
    return {
        "model_version": MODEL_VERSION,
        "artifact_id": artifact.artifact_id,
        "dataset_id": artifact.split.dataset_id,
        "source": artifact.split.source,
        "held_out_sha256": artifact_hash([record.model_dump(mode="json") for record in records]),
        "patients": len({record.patient_id for record in records}),
        "windows": len(records),
        "truth_counts": dict(truth_counts),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "drift_sensitivity": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "hypotension_false_drift": unsafe,
        "hypotension_windows": truth_counts["hypotension"],
        "hypotension_patients": len(hypo_patients),
        "zero_failure_patient_upper95": 1 - math.pow(0.05, 1 / len(hypo_patients))
        if hypo_patients and unsafe == 0
        else None,
        "inputs_sufficient_windows": sum(
            record.score.extra.get("inputs_sufficient") is True for record in records
        ),
        "baseline_cuff_gap": {
            "tp": baseline_tp,
            "fp": baseline_fp,
            "hypotension_false_drift": baseline_unsafe,
        },
        "cause_confusion": dict(cause_confusion),
        "events_with_delay": len(measured),
        "events_missed_or_onset_missing": len(delays) - len(measured),
        "detection_delay_ms": sorted(measured),
        "clinical_gate": "eligible_for_review" if real_gate else "pending",
        "review_required": True,
    }
