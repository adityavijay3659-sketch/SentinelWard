"""Local VitalDB CSV/gzip replay with case-relative times and explicit episode epoch."""

from __future__ import annotations

import csv
import gzip
import math
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain, islice
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from sentinelward.contracts import BedId, CuffReading, Identifier, VitalsMessage
from sentinelward.m6 import EpisodeContext

TRACKS = {
    "abp": "SNUADC/ART",
    "ecg": "SNUADC/ECG_II",
    "ppg": "SNUADC/PLETH",
    "hr": "Solar8000/HR",
    "spo2": "Solar8000/PLETH_SPO2",
    "rr": "Solar8000/RR",
    "sys": "Solar8000/NIBP_SBP",
    "dia": "Solar8000/NIBP_DBP",
    "map": "Solar8000/NIBP_MBP",
}


class ReplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    patient_id: Identifier
    source: str = "vitaldb"
    bed_id: BedId
    context: EpisodeContext
    tracks: dict[str, str]
    duration_s: int = Field(ge=10, le=86_400)


@dataclass(frozen=True, slots=True)
class Track:
    times: array[float]
    values: array[float]
    duplicate_samples: int = 0
    conflicting_duplicates: int = 0

    def recent(self, at: float, age: float) -> tuple[float, float] | None:
        index = bisect_right(self.times, at) - 1
        if index < 0 or at - self.times[index] > age or not math.isfinite(self.values[index]):
            return None
        return self.times[index], self.values[index]

    def frame(self, second: int) -> list[float] | None:
        # Average each 8-ms bin when downsampling; missing bins stay missing.
        samples: list[float] = []
        for index in range(125):
            start, end = second + index / 125, second + (index + 1) / 125
            left = bisect_left(self.times, start - 1e-9)
            right = bisect_left(self.times, end - 1e-9)
            values = self.values[left:right]
            if values and all(math.isfinite(value) for value in values):
                samples.append(sum(values) / len(values))
            else:
                return None
        return samples


def read_track(path: Path, *, duration_s: int, waveform: bool) -> Track:
    """Read explicit timestamps or VitalDB's compact waveform Time column."""
    opener = gzip.open if path.suffix == ".gz" else open
    times: array[float] = array("d")
    values: array[float] = array("d")
    duplicates = conflicts = 0
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader, [])
        if (
            len(header) != 2
            or header[0] != "Time"
            or header[1] not in {"Values", *TRACKS.values(), "Solar8000/ART_MBP"}
        ):
            raise ValueError("VitalDB track must have Time and one recognized value column")
        prefix = list(islice(reader, 3))
        if not prefix:
            return Track(times, values)
        time_prefix = [float(row[0] or "nan") for row in prefix]
        fourth = next(reader, None)
        compact = waveform and fourth is not None and not math.isfinite(float(fourth[0] or "nan"))
        if compact:
            origin, interval, declared_end = time_prefix
            if not (
                origin == 0
                and 0 < interval <= 1 / 125
                and (not math.isfinite(declared_end) or declared_end > interval)
            ):
                raise ValueError("unsupported compact waveform clock or source rate below 125 Hz")
        else:
            origin, interval, declared_end = 0.0, 0.0, 0.0
        rows = chain(prefix, [fourth] if fourth is not None else [], reader)
        count = 0
        for index, row in enumerate(rows):
            if len(row) != 2:
                raise ValueError("track row must contain exactly two columns")
            count = index + 1
            if compact and index > 2 and row[0]:
                clock_end = float(row[0])
                if math.isfinite(clock_end):
                    if abs(index * interval - clock_end) > 2 * interval:
                        raise ValueError("compact end timestamp does not match sample clock")
                    declared_end = clock_end
            timestamp = origin + index * interval if compact else float(row[0] or "nan")
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("invalid track timestamp")
            if timestamp >= duration_s:
                break
            value = float(row[1] or "nan")
            if times and timestamp < times[-1]:
                raise ValueError("track timestamps must be strictly increasing")
            if times and timestamp == times[-1]:
                # The public numeric API contains repeated timestamps. Identical
                # samples collapse; conflicting observations are unusable, not
                # arbitrarily selected as clinical evidence.
                duplicates += 1
                if value != values[-1]:
                    conflicts += 1
                    values[-1] = math.nan
                continue
            times.append(timestamp)
            values.append(value)
        else:
            if compact and (
                not math.isfinite(declared_end)
                or abs((count - 1) * interval - declared_end) > 2 * interval
            ):
                raise ValueError("compact track length does not match declared end")
    return Track(times, values, duplicates, conflicts)


def replay_vitaldb(manifest: ReplayManifest, root: Path) -> Iterator[VitalsMessage]:
    if manifest.context.start_ts % 1000:
        raise ValueError("episode start must align to whole seconds")
    tracks: dict[str, Track] = {}
    for name, relative in manifest.tracks.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("track path escapes the dataset directory")
        tracks[name] = read_track(
            path,
            duration_s=manifest.duration_s,
            waveform=name in {TRACKS[key] for key in ("abp", "ecg", "ppg")},
        )
    if TRACKS["abp"] not in tracks:
        raise ValueError("SNUADC/ART is required for VitalDB replay")
    last_cuff = -1.0
    last_cuff_values: tuple[float, float, float] | None = None
    for second in range(manifest.duration_s):

        def waveform(key: str, at: int = second) -> list[float] | None:
            track = tracks.get(TRACKS[key])
            return track.frame(at) if track is not None else None

        def scalar(key: str, at: int = second) -> float | None:
            track = tracks.get(TRACKS[key])
            value = track.recent(at, 5) if track is not None else None
            return value[1] if value is not None else None

        cuff_parts = [
            tracks[TRACKS[key]].recent(second, 1) if TRACKS[key] in tracks else None
            for key in ("sys", "dia", "map")
        ]
        nibp = None
        if all(part is not None for part in cuff_parts):
            parts = [part for part in cuff_parts if part is not None]
            if max(part[0] for part in parts) - min(part[0] for part in parts) <= 0.001:
                cuff_time = parts[2][0]
                cuff_values = (parts[0][1], parts[1][1], parts[2][1])
                sys, dia, pressure = cuff_values
                # Monitor numeric tracks repeat held NIBP values. A repeated
                # sample is NOT evidence of a newly acquired cuff measurement.
                if (
                    cuff_time > last_cuff
                    and cuff_values != last_cuff_values
                    and 0 < dia <= pressure <= sys <= 350
                ):
                    nibp = CuffReading(
                        sys=parts[0][1],
                        dia=parts[1][1],
                        map=parts[2][1],
                        ts=manifest.context.start_ts + round(cuff_time * 1000),
                    )
                    last_cuff = cuff_time
                    last_cuff_values = cuff_values
        yield VitalsMessage(
            v=1,
            type="vitals",
            bed_id=manifest.bed_id,
            device_id=manifest.context.device_id,
            seq=second,
            ts=manifest.context.start_ts + second * 1000,
            fs=125,
            ecg=waveform("ecg"),
            ppg=waveform("ppg"),
            abp=waveform("abp"),
            hr=scalar("hr"),
            spo2=scalar("spo2"),
            rr=scalar("rr"),
            nibp=nibp,
            monitor_alarm=None,
        )


def replay_jsonl(path: Path) -> Iterator[VitalsMessage]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield VitalsMessage.model_validate_json(line)
                except ValueError as exc:
                    raise ValueError(f"invalid vitals on JSONL line {line_number}") from exc
