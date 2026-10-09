"""Causal, deterministic M6 research scorer. Scores are evidence indices, not probabilities."""

from __future__ import annotations

import hashlib
import json
import math
from itertools import pairwise
from statistics import fmean, median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from sentinelward.contracts import (
    BedId,
    CuffReading,
    DeviceId,
    Identifier,
    ScoreMessage,
    VitalsMessage,
)

MODEL_VERSION: Literal["m6-research-0.3.1"] = "m6-research-0.3.1"


def feature_config_id(config: M6Config) -> str:
    data = config.model_dump(exclude={"evidence_threshold", "calibration_id"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class EpisodeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    episode_id: Identifier
    device_id: DeviceId
    start_ts: int = Field(ge=0)


class M6Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    baseline_seconds: int = Field(default=900, ge=900, le=3600)
    cuff_max_age_ms: int = Field(default=120_000, ge=0, le=300_000)
    gap_mmhg: FiniteFloat = Field(default=10, gt=0)
    ph_delta: FiniteFloat = Field(default=0.5, ge=0)
    ph_threshold: FiniteFloat = Field(default=30, gt=0)
    # Conservative research guards, NOT validated treatment thresholds.
    pressure_floor: FiniteFloat = Field(default=65, gt=0)
    pressure_fall: FiniteFloat = Field(default=15, gt=0)
    evidence_threshold: FiniteFloat = Field(default=0.6, gt=0, le=1)
    calibration_id: str | None = None


class Features(BaseModel):
    map: float
    amplitude: float
    shape: float
    hr: float | None
    pat_ms: float | None


class PageHinkley(BaseModel):
    positive: float = 0
    negative: float = 0

    def update(self, residual: float, delta: float) -> float:
        # Fixed healthy-baseline reference: adaptation must not absorb slow drift.
        self.positive = max(0.0, self.positive + residual - delta)
        self.negative = max(0.0, self.negative - residual - delta)
        return max(self.positive, self.negative)


class M6State(BaseModel):
    model_version: str = MODEL_VERSION
    context: EpisodeContext
    config: M6Config
    bed_id: BedId | None = None
    last_ts: int = -1
    last_seq: int = -1
    frames: list[VitalsMessage] = Field(default_factory=list)
    cuff: CuffReading | None = None
    baseline: list[Features] = Field(default_factory=list)
    baseline_first_ts: int | None = None
    baseline_last_ts: int | None = None
    ph: PageHinkley = Field(default_factory=PageHinkley)
    peers: list[ScoreMessage] = Field(default_factory=list)


def pulse_arrival(ecg: list[float], ppg: list[float]) -> float | None:
    """Simple ECG-peak to PPG-upstroke proxy; not a clinical PAT measurement."""
    ecg_span = max(ecg) - min(ecg)
    ppg_span = max(ppg) - min(ppg)
    if ecg_span <= 0.01 or ppg_span <= 0.001:
        return None
    threshold = min(ecg) + 0.7 * ecg_span
    peaks: list[int] = []
    for index in range(1, len(ecg) - 63):
        if (
            ecg[index] >= threshold
            and ecg[index] > ecg[index - 1]
            and ecg[index] >= ecg[index + 1]
            and (not peaks or index - peaks[-1] >= 30)
        ):
            peaks.append(index)
    delays = []
    for peak in peaks:
        index = max(range(peak + 10, peak + 63), key=lambda i: ppg[i] - ppg[i - 1])
        if ppg[index] - ppg[index - 1] > ppg_span * 0.005:
            delays.append((index - peak) * 8.0)
    return median(delays) if len(delays) >= 3 else None


def extract_features(frames: list[VitalsMessage]) -> Features | None:
    if len(frames) != 10 or any(frame.abp is None for frame in frames):
        return None
    abp = [sample for frame in frames for sample in (frame.abp or [])]
    if min(abp) < 0 or max(abp) > 350:
        return None
    ordered = sorted(abp)
    amplitude = ordered[int(len(abp) * 0.95)] - ordered[int(len(abp) * 0.05)]
    if amplitude < 1:
        return None
    ecg = [sample for frame in frames for sample in (frame.ecg or [])]
    ppg = [sample for frame in frames for sample in (frame.ppg or [])]
    hrs = [frame.hr for frame in frames if frame.hr is not None and 20 <= frame.hr <= 250]
    return Features(
        map=fmean(abp),
        amplitude=amplitude,
        shape=fmean(abs(b - a) for a, b in pairwise(abp)) / amplitude,
        hr=median(hrs) if len(hrs) == 10 else None,
        pat_ms=pulse_arrival(ecg, ppg) if len(ecg) == len(ppg) == 1250 else None,
    )


def predict_map(baseline: list[Features], current: Features) -> float:
    """Robustly centred, ridge-regularized 3-feature baseline, fitted only on warmup."""
    targets = [row.map for row in baseline]
    intercept = median(targets)
    rows = [[row.hr or 0, row.pat_ms or 0, row.amplitude] for row in baseline]
    centres = [median(row[j] for row in rows) for j in range(3)]
    scales = [max(1.0, median(abs(row[j] - centres[j]) for row in rows) * 1.4826) for j in range(3)]
    x = [[max(-5.0, min(5.0, (row[j] - centres[j]) / scales[j])) for j in range(3)] for row in rows]
    y = [max(-10.0, min(10.0, target - intercept)) for target in targets]
    # Solve (X'X + ridge*I)b = X'y using pivoted elimination.
    matrix = [
        [sum(row[i] * row[j] for row in x) + (10.0 if i == j else 0.0) for j in range(3)]
        + [sum(row[i] * target for row, target in zip(x, y, strict=True))]
        for i in range(3)
    ]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda i: abs(matrix[i][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        divisor = matrix[col][col]
        matrix[col] = [value / divisor for value in matrix[col]]
        for row in range(3):
            if row != col:
                factor = matrix[row][col]
                matrix[row] = [
                    a - factor * b for a, b in zip(matrix[row], matrix[col], strict=True)
                ]
    values = [current.hr or 0, current.pat_ms or 0, current.amplitude]
    adjustment = sum(
        matrix[j][3] * max(-5.0, min(5.0, (values[j] - centres[j]) / scales[j])) for j in range(3)
    )
    return intercept + max(-15.0, min(15.0, adjustment))


def step(state: M6State, message: VitalsMessage | ScoreMessage) -> ScoreMessage | None:
    """Mutate one episode state, returning at most one completed aligned score."""
    if state.bed_id is not None and state.bed_id != message.bed_id:
        raise ValueError("M6 episode state cannot mix beds")
    state.bed_id = message.bed_id
    if isinstance(message, ScoreMessage):
        if (
            message.model in {"M3", "M5"}
            and message.window_s == 10
            and message.window_start % 5000 == 0
            and message.window_start >= state.context.start_ts
        ):
            peers = {(peer.model, peer.window_start): peer for peer in state.peers}
            peers[(message.model, message.window_start)] = message
            state.peers = sorted(peers.values(), key=lambda item: item.window_start)[-24:]
        return None
    if message.device_id != state.context.device_id or message.ts < state.context.start_ts:
        raise ValueError("M6 frame does not match configured episode/device")
    if message.ts <= state.last_ts:
        return None  # Late/repeated frames never revise an already published window.
    if message.seq <= state.last_seq:
        raise ValueError("M6 sequence reset requires a new reviewed episode context")
    state.last_ts, state.last_seq = message.ts, message.seq
    state.frames = [frame for frame in state.frames if frame.ts > message.ts - 10_000]
    state.frames.append(message)
    if message.nibp is not None and (state.cuff is None or message.nibp.ts > state.cuff.ts):
        state.cuff = message.nibp
    end = message.ts + 1000
    if end % 5000 or end - 10_000 < state.context.start_ts:
        return None
    start = end - 10_000
    complete = [frame.ts for frame in state.frames] == list(range(start, end, 1000))
    features = extract_features(state.frames) if complete else None
    cuff = state.cuff
    fresh = (
        cuff is not None
        and 0 <= message.ts - cuff.ts <= state.config.cuff_max_age_ms
        and cuff.ts >= state.context.start_ts
    )
    needed = (state.config.baseline_seconds - 10) // 5 + 1
    extra: dict[str, object] = {
        "mode": "research",
        "score_kind": "evidence_index_not_probability",
        "calibration_id": state.config.calibration_id,
        "clinical_validation": "pending",
        "inputs_sufficient": False,
        "cuff_fresh": fresh,
        "cause_hint": "uncertain",
        "emergency_compatible": False,
        "baseline_windows": len(state.baseline),
        "baseline_required_windows": needed,
        "baseline_ready": len(state.baseline) >= needed,
        "assessment_path": "unavailable",
        "feature_config_id": feature_config_id(state.config),
        "drift_candidate": False,
        "frames_received": len(state.frames),
        "shape": "unavailable",
    }

    def output(label: str, reason: str, score: float = 0) -> ScoreMessage:
        extra["readiness_reason"] = (
            "patient_review_precedence"
            if label == "emergency_compatible"
            else "assessment_available"
            if extra["inputs_sufficient"]
            else "collecting_baseline"
            if label == "warming_up"
            else "required_evidence_unavailable"
        )
        return ScoreMessage(
            v=1,
            type="score",
            bed_id=message.bed_id,
            model="M6",
            model_version=MODEL_VERSION,
            window_start=start,
            window_s=10,
            score=score,
            label=label,
            reason=reason,
            extra=extra,
        )

    if features is not None:
        extra["art_map_mmhg"] = round(features.map, 3)
        extra["features"] = features.model_dump(mode="json")
        if fresh and cuff is not None:
            extra["gap_mmhg"] = round(features.map - cuff.map, 3)
    if fresh and cuff is not None:
        extra.update(cuff_map_mmhg=cuff.map, cuff_ts=cuff.ts, cuff_age_ms=message.ts - cuff.ts)
    if any(
        frame.monitor_alarm is not None and frame.monitor_alarm.priority == "high"
        for frame in state.frames
    ):
        extra["emergency_compatible"] = True
        return output(
            "emergency_compatible", "High-priority monitor alarm; immediate patient review needed"
        )
    if fresh and cuff is not None and cuff.map <= state.config.pressure_floor:
        extra["emergency_compatible"] = True
        return output(
            "emergency_compatible", "Low cuff pressure observed; immediate patient review needed"
        )
    if features is None:
        return output(
            "insufficient_data",
            "Pressure waveform missing, incomplete or unusable; drift cannot be assessed",
        )
    base_map = median(row.map for row in state.baseline) if state.baseline else features.map
    falling = features.map <= base_map - state.config.pressure_fall
    confirmed_fall = (
        fresh
        and cuff is not None
        and (
            cuff.map <= state.config.pressure_floor
            or (bool(state.baseline) and cuff.map <= base_map - state.config.pressure_fall)
            or (falling and abs(features.map - cuff.map) < state.config.gap_mmhg)
        )
    )
    # Conservative guard: low ART, cuff-confirmed fall, or any substantial fall.
    # This knowingly reduces negative-offset sensitivity until clinical review.
    if features.map <= state.config.pressure_floor or confirmed_fall or falling:
        extra["emergency_compatible"] = True
        return output(
            "emergency_compatible", "Possible patient deterioration; do not dismiss as sensor drift"
        )
    if not fresh or cuff is None:
        return output(
            "insufficient_data", "Fresh cuff reading unavailable; drift cannot be confirmed"
        )
    gap = features.map - cuff.map
    # A contemporaneous pressure/cuff disagreement is useful evidence even
    # during cold start. Never fabricate regression/PAT/PH evidence to emit it.
    # Existing alarm, absolute-pressure and relative-fall guards run FIRST.
    if abs(gap) >= state.config.gap_mmhg and (
        len(state.baseline) < needed or features.hr is None or features.pat_ms is None
    ):
        evidence = min(abs(gap) / (2 * state.config.gap_mmhg), 1.0)
        extra.update(
            inputs_sufficient=True,
            drift_candidate=True,
            assessment_path="cuff_gap_only",
            evidence_threshold=state.config.evidence_threshold,
            baseline_assessment_available=False,
        )
        return output(
            "drift" if evidence >= state.config.evidence_threshold else "insufficient_data",
            "ART and cuff disagree; combined assessment unavailable; review patient and sensor",
            evidence,
        )
    if features.hr is None or features.pat_ms is None:
        return output(
            "insufficient_data",
            "HR or ECG-to-pulse timing unavailable; baseline assessment incomplete",
        )
    if len(state.baseline) < needed:
        if state.baseline_last_ts is None or start - state.baseline_last_ts >= 5000:
            state.baseline.append(features)
            state.baseline_first_ts = (
                state.baseline_first_ts if state.baseline_first_ts is not None else start
            )
            state.baseline_last_ts = start
        extra["baseline_windows"] = len(state.baseline)
        extra["baseline_ready"] = len(state.baseline) >= needed
        return output(
            "warming_up", "Collecting usable patient baseline; drift assessment not ready"
        )
    predicted = predict_map(state.baseline, features)
    residual = features.map - predicted
    ph = state.ph.update(residual, state.config.ph_delta)
    shape_reference = median(row.shape for row in state.baseline)
    amp_reference = median(row.amplitude for row in state.baseline)
    shape_shift = abs(features.shape - shape_reference) / max(shape_reference, 0.0001)
    damped = features.amplitude < amp_reference * 0.6
    gap_evidence = (
        0.5 * min(abs(gap) / state.config.gap_mmhg, 1.0)
        + 0.35 * min(ph / state.config.ph_threshold, 1.0)
        + 0.15 * min(shape_shift, 1.0)
    )
    damping_strength = min(1.0, max(0.0, 1 - features.amplitude / amp_reference) / 0.4)
    morphology_evidence = 0.65 * damping_strength + 0.35 * min(shape_shift, 1.0)
    evidence = min(1.0, max(gap_evidence, morphology_evidence))
    assert math.isfinite(evidence)
    extra.update(
        inputs_sufficient=True,
        assessment_path="baseline_combined",
        baseline_assessment_available=True,
        predicted_map_mmhg=round(predicted, 3),
        residual_mmhg=round(residual, 3),
        page_hinkley=round(ph, 3),
        shape_shift=round(shape_shift, 3),
        damping_evidence=damped,
        drift_candidate=abs(gap) >= state.config.gap_mmhg or damped,
        evidence_threshold=state.config.evidence_threshold,
        shape="damping"
        if damped
        else "level_shift"
        if abs(gap) >= state.config.gap_mmhg and shape_shift < 0.25
        else "unchanged"
        if shape_shift < 0.25
        else "changed",
    )
    aligned = {peer.model: peer for peer in state.peers if peer.window_start == start}
    # Scores alone cannot prove intent. Use only explicit, reviewed peer labels.
    cause: Literal["sensor", "tampering", "uncertain"] = "uncertain"
    if set(aligned) == {"M3", "M5"}:
        if any(peer.label == "tampering" for peer in aligned.values()):
            cause = "tampering"
        elif all(peer.label == "normal" for peer in aligned.values()):
            cause = "sensor"
    extra["cause_hint"] = cause
    extra["aligned_peer_models"] = sorted(aligned)
    if extra["drift_candidate"] and evidence >= state.config.evidence_threshold:
        reason = (
            "Pressure disagrees with cuff and baseline; sensor review needed"
            if abs(gap) >= state.config.gap_mmhg
            else "Pressure pulse amplitude changed from baseline; sensor review needed"
        )
        return output("drift", reason, evidence)
    return output(
        "stable", "No drift evidence in this window; this is not a patient all-clear", evidence
    )
