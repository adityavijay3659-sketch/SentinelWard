from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_realdata import (
    REQUIRED,
    download,
    metrics,
    perturb,
    select_cases,
    selection_cases,
)
from sentinelward.m6_replay import ReplayManifest, read_track, replay_vitaldb


def test_official_track_header_and_end_timestamp_on_last_sample(tmp_path: Path) -> None:
    path = tmp_path / "api.csv"
    rows = ["Time,SNUADC/ART"]
    rows.extend(
        f"{0 if i == 0 else 0.002 if i == 1 else 0.998 if i == 499 else ''},85" for i in range(500)
    )
    path.write_text("\n".join(rows), encoding="utf-8")
    track = read_track(path, duration_s=2, waveform=True)
    assert len(track.times) == 500
    assert track.frame(0) == [85.0] * 125
    rows[-1] = "1.5,85"
    path.write_text("\n".join(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="end timestamp"):
        read_track(path, duration_s=2, waveform=True)


def test_numeric_duplicate_clock_never_chooses_conflicting_evidence(tmp_path: Path) -> None:
    path = tmp_path / "hr.csv"
    path.write_text("Time,Solar8000/HR\n0,80\n0,80\n1,81\n1,90\n2,82\n", encoding="utf-8")
    track = read_track(path, duration_s=10, waveform=False)
    assert track.duplicate_samples == 2 and track.conflicting_duplicates == 1
    assert track.recent(0, 1) == (0, 80)
    assert track.recent(1, 1) is None
    assert track.recent(2, 1) == (2, 82)


def test_download_is_bounded_resumable_and_detects_tampering(tmp_path: Path) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="Time,Solar8000/HR\n0,70\n1,71\n2,72\n3,73\n4,74\n5,75\n")

    path = tmp_path / "track.csv"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        receipt = download(client, "a" * 40, path, 4)
        assert path.read_text().splitlines()[-1] == "4,74"
        assert download(client, "a" * 40, path, 4) == receipt
        assert len(calls) == 1
        path.write_text("corrupt", encoding="utf-8")
        with pytest.raises(ValueError, match="integrity"):
            download(client, "a" * 40, path, 4)
        with pytest.raises(ValueError, match="invalid"):
            download(client, "../secrets", tmp_path / "x", 4)


def test_selection_groups_repeated_subjects_before_split() -> None:
    cases = [{"caseid": str(i), "subjectid": str(i // 2), "caseend": "4000"} for i in range(30)]
    tracks = [
        {"caseid": case["caseid"], "tname": name, "tid": "a" * 40}
        for case in cases
        for name in REQUIRED
    ]
    selected = select_cases(cases, tracks, 12, 3600)
    assert len({case["patient_id"] for case in selected}) == 12
    assert selected == select_cases(cases, tracks, 12, 3600)


def test_cohort_rejects_path_escape_and_repeated_subjects() -> None:
    cases = [{"case_id": str(i), "patient_id": f"vitaldb-subject-{i}"} for i in range(6)]
    assert selection_cases({"count": 6, "cases": cases}) == cases
    cases[0]["patient_id"] = "../../outside"
    with pytest.raises(ValueError, match="path identifier"):
        selection_cases({"count": 6, "cases": cases})
    cases[0]["patient_id"] = cases[1]["patient_id"]
    with pytest.raises(ValueError, match="repeated subjects"):
        selection_cases({"count": 6, "cases": cases})


def test_perturbation_is_causal_and_preserves_cuff() -> None:
    frame = synthetic_frame(100)
    assert perturb(frame, "offset_plus_15", 101_000) is frame
    changed = perturb(frame, "offset_plus_15", 100_000)
    assert changed.nibp == frame.nibp
    assert changed.ecg == frame.ecg and changed.ppg == frame.ppg
    assert changed.abp is not None and frame.abp is not None
    assert changed.abp[0] == pytest.approx(frame.abp[0] + 15)
    assert frame.abp[0] != changed.abp[0]


def test_monitor_held_cuff_does_not_refresh_and_invalid_cuff_is_missing(tmp_path: Path) -> None:
    (tmp_path / "art.csv").write_text("Time,SNUADC/ART\n0,85\n1,85\n", encoding="utf-8")
    tracks = {"SNUADC/ART": "art.csv"}
    for name, value in (("SBP", 110), ("DBP", 65), ("MBP", 85)):
        path = tmp_path / f"{name}.csv"
        path.write_text(
            f"Time,Solar8000/NIBP_{name}\n0,{value}\n2,{value}\n4,0\n", encoding="utf-8"
        )
        tracks[f"Solar8000/NIBP_{name}"] = path.name
    manifest = ReplayManifest.model_validate(
        {
            "patient_id": "subject1",
            "bed_id": "B01",
            "context": {"episode_id": "test", "device_id": "MON-01", "start_ts": 0},
            "tracks": tracks,
            "duration_s": 10,
        }
    )
    frames = list(replay_vitaldb(manifest, tmp_path))
    assert [frame.seq for frame in frames if frame.nibp is not None] == [0]


def test_insufficient_windows_remain_in_experiment_denominator() -> None:
    rows = [
        {
            "patient_id": "p1",
            "variant": "offset_plus_15",
            "onset_ms": 0,
            "score": {
                "score": 1,
                "window_start": 0,
                "label": "insufficient_data",
                "extra": {"inputs_sufficient": False, "drift_candidate": True},
            },
        }
    ]
    fact = metrics(rows, 0.6)["offset_plus_15"]
    assert fact["windows"] == 1 and fact["drift_predictions"] == 0
    assert fact["patients"] == 1 and fact["patients_with_drift_prediction"] == 0
    assert json.dumps(fact)
