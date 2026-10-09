from __future__ import annotations

import json

import pytest

from sentinelward.contracts import CuffReading, ScoreMessage, VitalsMessage, parse_wire_message
from sentinelward.errors import ContractError
from sentinelward.m6 import (
    EpisodeContext,
    Features,
    M6Config,
    M6State,
    PageHinkley,
    extract_features,
    predict_map,
    step,
)
from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_persistence import InMemoryM6Handler, restored_state
from sentinelward.presentation import render_line, wire_output_views


def ready_state() -> M6State:
    features = extract_features([synthetic_frame(i) for i in range(10)])
    assert features is not None and features.pat_ms is not None
    return M6State(
        context=EpisodeContext(episode_id="test-episode", device_id="MON-01", start_ts=0),
        config=M6Config(),
        baseline=[features] * 179,
        baseline_first_ts=0,
        baseline_last_ts=890_000,
    )


def score_window(state: M6State, **options: object) -> ScoreMessage:
    score = None
    for second in range(900, 910):
        frame = synthetic_frame(second)
        data = frame.model_dump(mode="json")
        if "pressure" in options:
            assert frame.abp is not None
            data["abp"] = [value + float(options["pressure"]) - 85 for value in frame.abp]
        if "cuff" in options:
            cuff = options["cuff"]
            data["nibp"] = (
                None
                if cuff is None
                else {
                    "sys": float(cuff) + 25,
                    "dia": float(cuff) - 20,
                    "map": cuff,
                    "ts": second * 1000,
                }
                if second == 900
                else None
            )
        if options.get("missing_abp"):
            data["abp"] = None
        if options.get("missing_ecg"):
            data["ecg"] = None
        if options.get("damping"):
            data["abp"] = [85 + (value - 85) / 5 for value in data["abp"]]
        if options.get("alarm"):
            data["monitor_alarm"] = {"code": "TEST", "priority": "high"}
        score = step(state, VitalsMessage.model_validate(data)) or score
    assert score is not None and score.window_start == 900_000
    return score


def test_locked_vitals_roundtrip_and_nonfinite_rejection() -> None:
    frame = synthetic_frame(0)
    assert parse_wire_message("ward/bed/B01/vitals", frame.model_dump_json().encode()) == frame
    for replacement in ([0] * 124, [float("nan")] * 125, [float("inf")] * 125):
        payload = frame.model_dump(mode="json") | {"abp": replacement}
        with pytest.raises(ContractError) as error:
            parse_wire_message("ward/bed/B01/vitals", json.dumps(payload).encode())
        assert error.value.code == "SCHEMA_INVALID"
    with pytest.raises(ValueError, match="future"):
        VitalsMessage.model_validate(
            frame.model_dump() | {"nibp": CuffReading(sys=100, dia=60, map=80, ts=1000)}
        )


def test_score_metadata_and_timestamp_range_are_safe_for_storage_and_projection() -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        ScoreMessage(
            v=1,
            type="score",
            bed_id="B01",
            model="M6",
            model_version="test",
            window_start=0,
            window_s=10,
            score=0.5,
            label="drift",
            reason="Test evidence",
            extra={"nested": [float("nan")]},
        )
    with pytest.raises(ValueError):
        VitalsMessage.model_validate(synthetic_frame(0).model_dump() | {"ts": 10**100})


def test_exact_window_alignment_missing_frame_and_late_input() -> None:
    state = M6State(context=ready_state().context, config=M6Config())
    scores = []
    for second in range(20):
        if second == 6:
            continue
        output = step(state, synthetic_frame(second))
        if output is not None:
            scores.append(output)
    assert [score.window_start for score in scores] == [0, 5000, 10_000]
    assert scores[0].label == scores[1].label == "insufficient_data"
    assert scores[2].label == "warming_up"
    saved = state.model_dump()
    assert step(state, synthetic_frame(6)) is None
    assert state.model_dump() == saved


def test_full_15_minute_baseline_freezes_before_drift_scoring() -> None:
    state = M6State(context=ready_state().context, config=M6Config())
    output = None
    for second in range(905):
        output = step(state, synthetic_frame(second)) or output
    assert output is not None and output.label == "stable"
    assert len(state.baseline) == 179
    assert state.baseline_last_ts == 890_000
    assert state.ph.positive < 1e-8


def test_level_shift_and_damping_are_detected_with_bounded_outputs() -> None:
    for options in ({"pressure": 100}, {"damping": True}):
        score = score_window(ready_state(), **options)
        assert score.label == "drift"
        assert score.extra["inputs_sufficient"] is True
        assert 0.6 <= score.score <= 1
        views = wire_output_views(score)
        assert "WARNING" in views.user and "RESEARCH" in views.team
        assert all(len(line) <= 160 and "\n" not in line for line in views.lines())
        assert views.model == score.model_dump(mode="json")


@pytest.mark.parametrize(
    "options",
    [
        {"pressure": 55, "cuff": 55},
        {"pressure": 65, "cuff": None},
        {"pressure": 68, "cuff": 85},
        {"pressure": 100, "cuff": 68},
        {"cuff": 55, "missing_abp": True},
        {"alarm": True, "missing_abp": True},
    ],
)
def test_possible_deterioration_takes_precedence_over_missing_or_drift(
    options: dict[str, object],
) -> None:
    score = score_window(ready_state(), **options)
    assert score.label == "emergency_compatible"
    assert score.extra["emergency_compatible"] is True
    assert score.extra["drift_candidate"] is False
    assert "URGENT" in wire_output_views(score).user


@pytest.mark.parametrize("options", [{"cuff": None}, {"missing_abp": True}, {"missing_ecg": True}])
def test_missing_inputs_never_report_stable(options: dict[str, object]) -> None:
    assert score_window(ready_state(), **options).label == "insufficient_data"


def test_expired_cuff_is_not_reused_as_fresh_drift_evidence() -> None:
    state = ready_state()
    state.cuff = CuffReading(sys=110, dia=65, map=85, ts=779_000)
    score = score_window(state, pressure=100, cuff=None)
    assert score.label == "insufficient_data" and score.extra["cuff_fresh"] is False
    assert "gap_mmhg" not in score.extra


def test_aligned_peer_evidence_cause_is_a_hint_not_a_verdict() -> None:
    state = ready_state()
    for model in ("M3", "M5"):
        step(
            state,
            ScoreMessage(
                v=1,
                type="score",
                bed_id="B01",
                model=model,
                model_version="test",
                window_start=900_000,
                window_s=10,
                score=0.9,
                label="tampering",
                reason="Test evidence",
                extra={},
            ),
        )
    score = score_window(state, pressure=100)
    assert score.extra["cause_hint"] == "tampering"
    assert score_window(ready_state(), pressure=100).extra["cause_hint"] == "uncertain"
    # Network evidence cannot suppress a supported patient fall.
    emergency_state = ready_state()
    emergency_state.peers = state.peers
    assert score_window(emergency_state, pressure=55, cuff=55).label == "emergency_compatible"


def test_fixed_baseline_residual_reference_and_robust_regression() -> None:
    baseline = [Features(map=85, amplitude=40, shape=0.01, hr=60, pat_ms=160)] * 179
    baseline[-1] = Features(map=250, amplitude=40, shape=0.01, hr=60, pat_ms=160)
    assert predict_map(baseline, baseline[0]) == 85
    ph = PageHinkley()
    values = [ph.update(-2, 0.5) for _ in range(30)]
    assert values[-1] == 45
    assert ph.negative > ph.positive


@pytest.mark.asyncio
async def test_restart_replay_and_episode_reset_do_not_reuse_patient_state() -> None:
    contexts = {"B01": ready_state().context}
    handler = InMemoryM6Handler(contexts)
    for second in range(9):
        await handler.handle_m6(synthetic_frame(second))
    restarted = InMemoryM6Handler(contexts, states=handler.states, outbox=handler.outbox)
    assert await restarted.handle_m6(synthetic_frame(9)) is not None
    assert await restarted.handle_m6(synthetic_frame(9)) is None
    assert len(restarted.outbox) == 1
    contexts["B01"] = EpisodeContext(episode_id="next-patient", device_id="MON-01", start_ts=20_000)
    await restarted.handle_m6(synthetic_frame(20).model_copy(update={"seq": 0}))
    state = M6State.model_validate(restarted.states["B01"])
    assert len(state.baseline) == 0 and state.ph.positive == 0
    with pytest.raises(ValueError, match="episode"):
        await restarted.handle_m6(synthetic_frame(19))
    with pytest.raises(ValueError, match="configuration"):
        restored_state(state.model_dump(), state.context, M6Config(ph_threshold=31))


def test_sequence_reset_device_swap_and_mixed_beds_require_context() -> None:
    state = ready_state()
    step(state, synthetic_frame(900))
    with pytest.raises(ValueError, match="sequence reset"):
        step(state, synthetic_frame(901).model_copy(update={"seq": 0}))
    with pytest.raises(ValueError, match="device"):
        step(state, synthetic_frame(901).model_copy(update={"device_id": "MON-02"}))
    with pytest.raises(ValueError, match="mix beds"):
        step(state, synthetic_frame(901, bed_id="B02"))


def test_projection_preserves_urgency_and_result_for_extreme_fixed_fields() -> None:
    line = render_line(
        timestamp_ms=0,
        subject="B01" * 100,
        source_event="EMERGENCY " + "EVENT" * 100,
        key_fact="fact" * 100,
        result="FAILED " + "DETAIL" * 100,
    )
    assert len(line) <= 160 and "EMERGENCY" in line and "FAILED" in line
    assert "\n" not in line and "\u202e" not in wire_output_views(synthetic_frame(0)).team
