"""Deterministic synthetic scenarios for software verification only."""

from __future__ import annotations

import math
import time
from statistics import median
from typing import Literal

from sentinelward.contracts import CuffReading, MonitorAlarm, ScoreMessage, VitalsMessage
from sentinelward.m6 import EpisodeContext, M6Config, M6State, step
from sentinelward.m6_evaluation import LabelledWindow, SplitManifest, calibrate, evaluate
from sentinelward.presentation import wire_output_views


def synthetic_frame(
    second: int,
    *,
    bed_id: str = "B01",
    pressure: float = 85,
    cuff: float | None = 85,
    amplitude: float = 20,
    missing_abp: bool = False,
    alarm: bool = False,
) -> VitalsMessage:
    ecg = [1.0 if index == 5 else 0.0 for index in range(125)]
    ppg = [
        0.0 if index < 25 else (index - 25) / 10 if index < 35 else max(0.0, 1 - (index - 35) / 75)
        for index in range(125)
    ]
    return VitalsMessage(
        v=1,
        type="vitals",
        bed_id=bed_id,
        device_id=f"MON-{bed_id[1:]}",
        seq=second,
        ts=second * 1000,
        fs=125,
        ecg=ecg,
        ppg=ppg,
        abp=None
        if missing_abp
        else [pressure + amplitude * math.sin(index * math.tau / 125) for index in range(125)],
        hr=60,
        spo2=98,
        rr=16,
        nibp=CuffReading(sys=cuff + 25, dia=cuff - 20, map=cuff, ts=second * 1000)
        if cuff is not None and second % 30 == 0
        else None,
        monitor_alarm=MonitorAlarm(code="TEST_HIGH", priority="high") if alarm else None,
    )


def scenario(
    name: str, patient_id: str, *, bed_id: str = "B01"
) -> tuple[list[LabelledWindow], list[float]]:
    state = M6State(
        context=EpisodeContext(episode_id=patient_id, device_id=f"MON-{bed_id[1:]}", start_ts=0),
        config=M6Config(),
    )
    duration = 1220 if name == "ramp" else 980
    records = []
    latency = []
    for second in range(duration):
        active = second >= 900
        pressure, amplitude = 85.0, 20.0
        cuff: float | None = 85.0
        if active and name in {"level", "tampering"}:
            pressure += 15
        elif active and name == "ramp":
            pressure += min(15, (second - 900) / 300 * 15)
        elif active and name == "hypotension":
            pressure = cuff = 55
        elif active and name == "damping":
            amplitude = 4
        elif active and name == "missing_cuff":
            cuff = None
        start = (second + 1) * 1000 - 10_000
        if start >= 0 and start % 5000 == 0:
            for model in ("M3", "M5"):
                step(
                    state,
                    ScoreMessage(
                        v=1,
                        type="score",
                        bed_id=bed_id,
                        model=model,
                        model_version="synthetic-peer",
                        window_start=start,
                        window_s=10,
                        score=0.9 if name == "tampering" and active else 0.1,
                        label="tampering" if name == "tampering" and active else "normal",
                        reason="Synthetic peer evidence",
                        extra={},
                    ),
                )
        frame = synthetic_frame(
            second,
            bed_id=bed_id,
            pressure=pressure,
            cuff=cuff,
            amplitude=amplitude,
            missing_abp=active and name == "missing_abp",
            alarm=active and name == "high_alarm",
        )
        before = time.perf_counter()
        score = step(state, frame)
        latency.append((time.perf_counter() - before) * 1000)
        if score is not None and score.window_start >= 900_000:
            truth: Literal["stable", "drift", "tampering", "hypotension"] = (
                "hypotension"
                if name == "hypotension"
                else "tampering"
                if name == "tampering"
                else "drift"
                if name in {"level", "ramp", "damping"}
                else "stable"
            )
            records.append(
                LabelledWindow(
                    patient_id=patient_id,
                    event_id=f"{patient_id}:{name}",
                    onset_ms=900_000,
                    truth=truth,
                    score=score,
                )
            )
    return records, latency


def run_demo() -> dict[str, object]:
    validation: list[LabelledWindow] = []
    held_out: list[LabelledWindow] = []
    latencies = []
    examples: dict[str, object] = {}
    validation_patients: list[str] = []
    test_patients: list[str] = []
    scenarios = ("stable", "level", "hypotension", "damping", "ramp", "tampering")
    for group in ("validation", "test"):
        for index, name in enumerate(scenarios):
            patient = f"synthetic-{group}-{name}"
            (validation_patients if group == "validation" else test_patients).append(patient)
            records, latency = scenario(
                name, patient, bed_id=f"B{index + (1 if group == 'validation' else 7):02}"
            )
            (validation if group == "validation" else held_out).extend(records)
            latencies.extend(latency)
            if group == "test":
                examples[name] = wire_output_views(records[-1].score).as_dict()
    split = SplitManifest(
        dataset_id="synthetic-software-harness-v1",
        source="synthetic",
        train=["synthetic-training-reserved"],
        validation=validation_patients,
        test=test_patients,
    )
    artifact = calibrate(validation, split)
    report = evaluate(held_out, artifact)
    ordered = sorted(latencies)
    report.update(
        synthetic_only=True,
        bed_count=12,
        latency_scope="in-process sequential scorer; excludes database, MQTT and transport",
        scorer_latency_median_ms=median(ordered),
        scorer_latency_p95_ms=ordered[int(len(ordered) * 0.95)],
        scorer_latency_max_ms=max(ordered),
        outputs=examples,
        calibration_threshold=artifact.config.evidence_threshold,
    )
    return report
