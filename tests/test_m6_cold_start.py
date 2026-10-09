from __future__ import annotations

import pytest

from sentinelward.m6 import EpisodeContext, M6Config, M6State, step
from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_persistence import restored_state
from sentinelward.presentation import wire_output_views


def window(pressure: float, cuff: float | None, missing_ecg: bool = False):
    state = M6State(
        context=EpisodeContext(episode_id="cold", device_id="MON-01", start_ts=0), config=M6Config()
    )
    result = None
    for second in range(10):
        frame = synthetic_frame(second, pressure=pressure, cuff=cuff)
        if missing_ecg:
            frame = frame.model_copy(update={"ecg": None})
        result = step(state, frame) or result
    assert result is not None
    return state, result


def test_cold_start_gap_assessment_does_not_wait_for_15_minute_regression() -> None:
    state, score = window(100, 85, missing_ecg=True)
    assert score.label == "drift" and score.score == 0.75
    assert score.extra["assessment_path"] == "cuff_gap_only"
    assert score.extra["baseline_ready"] is False and not state.baseline
    assert "predicted_map_mmhg" not in score.extra and "page_hinkley" not in score.extra
    assert score.extra["clinical_validation"] == "pending"
    assert "WARNING" in wire_output_views(score).user
    assert "GAP-ONLY" in wire_output_views(score).team


def test_gap_only_requires_actual_fresh_reference_and_never_trains_disagreement() -> None:
    state, score = window(100, None)
    assert score.label == "insufficient_data" and not state.baseline
    assert score.extra["inputs_sufficient"] is False
    state, score = window(100, 85)
    assert not state.baseline and score.extra["baseline_assessment_available"] is False


def test_low_pressure_and_alarm_precedence_remain_urgent_during_cold_start() -> None:
    for pressure, cuff in ((55, 85), (100, 55), (55, 55)):
        _, score = window(pressure, cuff)
        assert score.label == "emergency_compatible"
        assert score.extra["drift_candidate"] is False
        assert "URGENT" in wire_output_views(score).user


def test_gap_below_threshold_does_not_invent_normal_or_high_combined_score() -> None:
    _, score = window(96, 85)
    assert score.score == 0.55 and score.label == "insufficient_data"
    assert score.extra["assessment_path"] == "cuff_gap_only"
    assert "PRESSURE GAP" in wire_output_views(score).user
    assert "DATA MISSING" not in wire_output_views(score).user


def test_algorithm_upgrade_requires_new_episode_not_reusing_old_patient_state() -> None:
    state, _ = window(85, 85)
    raw = state.model_dump(mode="json")
    raw.pop("model_version")
    with pytest.raises(ValueError, match="algorithm version"):
        restored_state(raw, state.context, state.config)
    new = EpisodeContext(episode_id="next-version", device_id="MON-01", start_ts=20_000)
    restored = restored_state(raw, new, state.config)
    assert restored.context == new and not restored.baseline
