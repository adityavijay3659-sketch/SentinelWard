from __future__ import annotations

import csv
import gzip
import json
import math
from pathlib import Path

import pytest

from sentinelward.cli import main
from sentinelward.m6 import EpisodeContext
from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_replay import ReplayManifest, read_track, replay_vitaldb


def write_csv(path: Path, rows: list[tuple[object, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Time", "Values"])
        writer.writerows(rows)


def test_vitaldb_compact_waveform_clock_and_gzip_missing_bin(tmp_path: Path) -> None:
    path = tmp_path / "wave.csv"
    rows = [(0 if i == 0 else 0.002 if i == 1 else 0.998 if i == 2 else "", i) for i in range(500)]
    write_csv(path, rows)
    track = read_track(path, duration_s=1, waveform=True)
    assert list(track.times[:3]) == [0, 0.002, 0.004]
    assert track.frame(0) is not None
    assert track.frame(0)[0] == pytest.approx(1.5)
    compressed = tmp_path / "wave.csv.gz"
    with gzip.open(compressed, "wb") as stream:
        stream.write(path.read_bytes())
    assert read_track(compressed, duration_s=1, waveform=True).frame(0) == track.frame(0)
    rows[200] = ("", "nan")
    write_csv(path, rows)
    assert read_track(path, duration_s=1, waveform=True).frame(0) is None


def test_vitaldb_replay_preserves_sparse_cuff_and_clock(tmp_path: Path) -> None:
    wave = tmp_path / "art.csv"
    write_csv(wave, [(i / 500, 85 + 20 * math.sin(i / 500 * math.tau)) for i in range(5000)])
    tracks = {"SNUADC/ART": wave.name}
    for suffix, value in (("SBP", 110), ("DBP", 65), ("MBP", 85)):
        path = tmp_path / f"{suffix}.csv"
        write_csv(path, [(0, value), (3, value + 1), (7, value + 2)])
        tracks[f"Solar8000/NIBP_{suffix}"] = path.name
    manifest = ReplayManifest(
        patient_id="case-1",
        bed_id="B01",
        duration_s=10,
        context=EpisodeContext(episode_id="case-1", device_id="MON-01", start_ts=10_000),
        tracks=tracks,
    )
    frames = list(replay_vitaldb(manifest, tmp_path))
    assert [frame.ts for frame in frames] == list(range(10_000, 20_000, 1000))
    assert [frame.seq for frame in frames if frame.nibp is not None] == [0, 3, 7]
    assert all(frame.hr is None and frame.ecg is None for frame in frames)
    assert all(frame.abp is not None and len(frame.abp) == 125 for frame in frames)


def test_loader_rejects_path_escape_and_noncausal_numeric_clock(tmp_path: Path) -> None:
    manifest = ReplayManifest(
        patient_id="case-1",
        bed_id="B01",
        duration_s=10,
        context=EpisodeContext(episode_id="case-1", device_id="MON-01", start_ts=0),
        tracks={"SNUADC/ART": "../other.csv"},
    )
    with pytest.raises(ValueError, match="escapes"):
        list(replay_vitaldb(manifest, tmp_path))
    path = tmp_path / "bad.csv"
    write_csv(path, [(0, 80), (1, 81), (0.5, 82)])
    with pytest.raises(ValueError, match="strictly increasing"):
        read_track(path, duration_s=10, waveform=False)


def test_sparse_single_cuff_event_is_valid_and_never_forward_filled_beyond_age(
    tmp_path: Path,
) -> None:
    path = tmp_path / "single.csv"
    write_csv(path, [(2.5, 85)])
    track = read_track(path, duration_s=10, waveform=False)
    assert track.recent(2, 1) is None
    assert track.recent(3, 1) == (2.5, 85)
    assert track.recent(5, 1) is None


@pytest.mark.parametrize("audience", ["user", "team", "model"])
def test_cli_jsonl_replay_uses_shared_views_without_database_or_secrets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    audience: str,
) -> None:
    data = tmp_path / "vitals.jsonl"
    context = tmp_path / "episode.json"
    data.write_text(
        "\n".join(synthetic_frame(second).model_dump_json() for second in range(20)),
        encoding="utf-8",
    )
    context.write_text(
        EpisodeContext(episode_id="test", device_id="MON-01", start_ts=0).model_dump_json(),
        encoding="utf-8",
    )
    main(["m6", "replay", "--input", str(data), "--context", str(context), "--view", audience])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    if audience == "model":
        assert [json.loads(line)["window_start"] for line in lines] == [0, 5000, 10_000]
        assert all(json.loads(line)["extra"]["mode"] == "research" for line in lines)
    else:
        assert all(len(line) <= 160 and "RESEARCH" in line for line in lines)
        if audience == "user":
            assert "SENSOR ASSESSMENT" in lines[0]
        else:
            assert "M6 WARMING_UP" in lines[0]
