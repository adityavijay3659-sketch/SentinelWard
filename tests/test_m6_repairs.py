from __future__ import annotations

from pathlib import Path

import pytest

from sentinelward.contracts import CuffReading
from sentinelward.m6 import EpisodeContext, M6Config, M6State, extract_features, step
from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_evaluation import calibrate, evaluate, validate_records
from sentinelward.m6_revalidation import ONSET, drift_metrics
from sentinelward.presentation import wire_output_views
from tests.test_m6_evaluation import records, split


def state_with_baseline() -> M6State:
    features = extract_features([synthetic_frame(i) for i in range(10)])
    assert features is not None
    return M6State(
        context=EpisodeContext(episode_id="repair", device_id="MON-01", start_ts=0),
        config=M6Config(),
        baseline=[features] * 179,
        baseline_first_ts=0,
        baseline_last_ts=890_000,
    )


def test_cuff_confirmed_relative_fall_stays_urgent_without_art() -> None:
    state = state_with_baseline()
    result = None
    for second in range(900, 910):
        result = step(state, synthetic_frame(second, cuff=70, missing_abp=True)) or result
    assert result is not None and result.label == "emergency_compatible"
    assert "URGENT" in wire_output_views(result).user


def test_low_flat_pressure_requires_patient_review_without_cuff() -> None:
    state = M6State(context=state_with_baseline().context, config=M6Config())
    result = None
    for second in range(10):
        frame = synthetic_frame(second, cuff=None).model_copy(update={"abp": [55.0] * 125})
        result = step(state, frame) or result
    assert result is not None and result.label == "emergency_compatible"
    assert result.extra["drift_candidate"] is False


def test_cold_start_observed_pressure_fall_is_not_misclassified_as_gap_drift() -> None:
    state = M6State(context=state_with_baseline().context, config=M6Config())
    result = None
    for second in range(10):
        pressure = 100 if second < 8 else 85
        frame = synthetic_frame(second, pressure=pressure, cuff=None)
        if second == 8:
            frame = frame.model_copy(update={"nibp": CuffReading(sys=110, dia=65, map=85, ts=8000)})
        result = step(state, frame) or result
    assert result is not None and result.label == "emergency_compatible"


def test_unknown_negative_windows_are_abstentions_not_true_negatives() -> None:
    artifact = calibrate(records("validation"), split())
    heldout = records("test")
    heldout[0].score.extra["inputs_sufficient"] = False
    report = evaluate(heldout, artifact)
    assert report["unassessed_windows"] == 1
    assert report["tn"] == 0
    assert report["false_positive_rate"] is None
    assert report["protected_patient_review_windows"] == 1


def test_unknown_hypotension_cannot_make_clinical_gate_eligible() -> None:
    manifest = split().model_copy(update={"source": "vitaldb", "labels_reviewed": True})
    artifact = calibrate(records("validation"), manifest)
    heldout = records("test")
    heldout[2].score.extra.update(inputs_sufficient=False, emergency_compatible=False)
    report = evaluate(heldout, artifact)
    assert report["clinical_gate"] == "pending"
    assert report["hypotension_unassessed_windows"] == 1


def test_onset_before_detection_is_required_for_positive_event_labels() -> None:
    labelled = records("validation")
    labelled[1] = labelled[1].model_copy(update={"onset_ms": 60_000})
    with pytest.raises(ValueError, match="onset"):
        validate_records(labelled, patients=["validation"], config=M6Config())


def test_paired_delay_never_credits_existing_reference_prediction() -> None:
    def row(variant: str, start: int, positive: bool) -> dict:
        return {
            "patient_id": "p",
            "variant": variant,
            "event_active": True,
            "score": {
                "window_start": start,
                "score": 0.8,
                "label": "drift",
                "extra": {
                    "inputs_sufficient": True,
                    "drift_candidate": positive,
                    "emergency_compatible": False,
                },
            },
        }

    data = [
        row("reference", ONSET, True),
        row("offset_plus_15", ONSET, True),
        row("reference", ONSET + 60_000, False),
        row("offset_plus_15", ONSET + 60_000, True),
    ]
    facts = drift_metrics(data, 0.6)["offset_plus_15"]
    assert facts["detection_delay_ms"] == {"p": 70_000}
    assert facts["subjects_with_drift_prediction"] == 1


def make_epoch_case(tmp_path: Path) -> EpisodeContext:
    import csv

    from sentinelward.m6_replay import ReplayManifest

    context = EpisodeContext(episode_id="epoch", device_id="MON-01", start_ts=1_000_000)
    tracks = {}
    channels = {
        "SNUADC/ART": "abp",
        "SNUADC/ECG_II": "ecg",
        "SNUADC/PLETH": "ppg",
    }
    for index, (name, channel) in enumerate(channels.items()):
        file = tmp_path / f"wave-{index}.csv"
        with file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Time", "Values"])
            for second in range(10):
                samples = getattr(synthetic_frame(second), channel)
                writer.writerows((second + i / 125, value) for i, value in enumerate(samples))
        tracks[name] = file.name
    for index, (name, value) in enumerate([("Solar8000/ART_MBP", 85), ("Solar8000/HR", 60)]):
        file = tmp_path / f"numeric-{index}.csv"
        with file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Time", "Values"])
            writer.writerows((second, value) for second in range(10))
        tracks[name] = file.name
    manifest = ReplayManifest(
        patient_id="epoch-patient", bed_id="B01", context=context, tracks=tracks, duration_s=10
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return context


def test_numeric_target_uses_case_relative_time_with_nonzero_epoch(tmp_path: Path) -> None:
    from sentinelward.m6_training import extract_case

    context = make_epoch_case(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    rows, quality = extract_case(tmp_path, output)
    assert len(rows) == 1 and quality["target_unusable_or_missing"] == 0
    assert rows[0]["window_start"] == context.start_ts
    assert rows[0]["target_ts"] == 9


def test_baseline_gap_restarts_collection_and_reports_actual_span() -> None:
    state = M6State(context=state_with_baseline().context, config=M6Config())
    result = None
    for second in range(20):
        result = step(state, synthetic_frame(second)) or result
    assert result is not None and result.extra["baseline_span_ms"] == 20_000
    for second in range(120, 130):
        result = step(state, synthetic_frame(second)) or result
    assert result is not None and result.label == "warming_up"
    assert len(state.baseline) == 1 and state.baseline_first_ts == 120_000
    assert result.extra["baseline_restarted_after_gap"] is True
    assert result.extra["baseline_span_ms"] == 10_000
    assert len(state.pressure_guard_reference) == 4


def test_baseline_restart_cannot_erase_an_earlier_pressure_fall_reference() -> None:
    state = M6State(context=state_with_baseline().context, config=M6Config())
    for second in range(20):
        step(state, synthetic_frame(second, pressure=100, cuff=100))
    for second in range(120, 130):
        step(state, synthetic_frame(second, pressure=90, cuff=90))
    assert len(state.baseline) == 1
    result = None
    for second in range(130, 140):
        result = step(state, synthetic_frame(second, pressure=80, cuff=80)) or result
    assert result is not None and result.label == "emergency_compatible"
    assert result.extra["pressure_guard_reference_mmhg"] == 100
    assert result.extra["baseline_ready"] is False


def test_new_urgent_guard_cannot_remove_an_observation_from_the_old_pressure_history() -> None:
    state = M6State(context=state_with_baseline().context, config=M6Config())
    result = None
    for second in range(10):
        result = (
            step(state, synthetic_frame(second, pressure=100 if second < 8 else 85, cuff=97))
            or result
        )
    assert result is not None and result.label == "emergency_compatible"
    assert not state.baseline  # Urgent data never enters the drift baseline.
    assert state.pressure_guard_reference == pytest.approx([97])
    for second in range(120, 130):
        result = step(state, synthetic_frame(second, pressure=82, cuff=82)) or result
    assert result is not None and result.label == "emergency_compatible"
    assert result.extra["pressure_guard_reference_mmhg"] == 97


def test_unassessed_stable_validation_cannot_dilute_false_positive_rate() -> None:
    labelled = records("validation")
    labelled[0].score.extra["inputs_sufficient"] = False
    with pytest.raises(ValueError, match="assessed stable"):
        calibrate(labelled, split())


def test_dataset_preflight_exposes_missing_baseline_and_unverified_cuff_clock(
    tmp_path: Path,
) -> None:
    from sentinelward.m6_quality import preflight

    make_epoch_case(tmp_path)
    report = preflight(manifest=tmp_path / "manifest.json")
    assert report["baseline_ready_patients"] == 0
    assert report["clinical_deployment_allowed"] is False
    case = report["cases"][0]
    assert case["windows"] == 1 and case["drift_assessment_coverage"] == 0
    assert case["blocking_inputs"]["fresh_cuff"] == 1
    assert case["cuff_time_provenance"] == "inferred_value_changes_not_verified_acquisition"
    assert case["tracks_without_receipts"] == 5


def test_nonzero_epoch_perturbation_preserves_first_15_minutes() -> None:
    from sentinelward.m6_revalidation import modify

    epoch = 1_000_000
    before = synthetic_frame(1).model_copy(update={"ts": epoch + 1000})
    at = synthetic_frame(900).model_copy(update={"ts": epoch + ONSET})
    assert modify(before, "offset_plus_15", epoch + ONSET) is before
    assert modify(at, "offset_plus_15", epoch + ONSET).abp != at.abp


def test_download_quota_stops_before_promoting_an_incomplete_track(tmp_path: Path) -> None:
    import httpx

    from sentinelward.m6_realdata import DownloadBudget, download

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="Time,Values\n0,80\n1,85\n2,90\n")
    )
    path = tmp_path / "track.csv"
    budget = DownloadBudget(tmp_path, limit_bytes=18, reserve_bytes=0)
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(ValueError, match="byte budget"),
    ):
        download(client, "a" * 40, path, duration=10, budget=budget)
    assert not path.exists() and not path.with_suffix(".receipt.json").exists()
    assert path.with_suffix(".part").stat().st_size <= 18


def test_pilot_configuration_rejects_invalid_split_before_creating_root(tmp_path: Path) -> None:
    from sentinelward.m6_cohort import build

    root = tmp_path / "bad-pilot"
    with pytest.raises(ValueError, match="subjects in triples"):
        build(tmp_path / "previous", root, count=7)
    assert not root.exists()
