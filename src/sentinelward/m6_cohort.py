"""New independent VitalDB cohort screened for reference availability, not model outcome."""

from __future__ import annotations

import argparse
import csv
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from sentinelward.m6 import EpisodeContext
from sentinelward.m6_cli import save_new
from sentinelward.m6_realdata import REQUIRED, DownloadBudget, checksum, download, selection_cases
from sentinelward.m6_replay import ReplayManifest, read_track


def build(
    previous: Path,
    root: Path,
    count: int = 12,
    duration: int = 7200,
    *,
    exclude_selections: tuple[Path, ...] = (),
    max_bytes: int = 10 * 1024**3,
    reserve_bytes: int = 30 * 1024**3,
) -> None:
    if count < 6 or count > 60 or count % 3 or not 900 <= duration <= 21_600:
        raise ValueError("cohort requires 6..60 subjects in triples and 900..21600 seconds")
    if max_bytes <= 0 or reserve_bytes < 0:
        raise ValueError("invalid cohort storage budget")
    old = json.loads((previous / "selection.json").read_text(encoding="utf-8"))
    excluded = {case["patient_id"] for case in selection_cases(old)}
    excluded_hashes = {}
    for path in exclude_selections:
        selection = json.loads(path.read_text(encoding="utf-8"))
        excluded.update(case["patient_id"] for case in selection_cases(selection))
        excluded_hashes[str(path)] = checksum(path)
    root.mkdir(parents=True, exist_ok=False)
    budget = DownloadBudget(root, max_bytes, reserve_bytes)
    budget.consume(0)
    with (previous / "cases.csv").open(encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    available: dict[str, dict[str, str]] = {}
    with (previous / "trks.csv").open(encoding="utf-8") as stream:
        for track in csv.DictReader(stream):
            if track["tname"] in REQUIRED:
                available.setdefault(track["caseid"], {})[track["tname"]] = track["tid"]
    candidates = [
        case
        for case in cases
        if float(case["caseend"]) >= duration
        and set(REQUIRED) <= set(available.get(case["caseid"], {}))
        and f"vitaldb-subject-{case['subjectid']}" not in excluded
    ]
    random.Random(20261010).shuffle(candidates)
    save_new(
        root / "screening-plan.json",
        {
            "seed": 20261010,
            "count": count,
            "duration_s": duration,
            "download_byte_budget": max_bytes,
            "disk_reserve_bytes": reserve_bytes,
            "additional_excluded_selection_sha256": excluded_hashes,
            "exclude_subjects": sorted(excluded),
            "criterion": (
                "at least 200 five-second windows with a changed cuff reference "
                "overlapping arterial numeric availability after 900s"
            ),
            "minimum_reference_windows": 200,
            "reference_age_seconds": 120,
            "maximum_candidates": 180,
            "clinical_pressure_labels_used_for_selection": False,
            "reference_screening_is_not_combined_baseline_readiness": True,
            "next_gate": "m6 preflight on raw waveforms before training",
            "previous_metadata_sha256": {
                name: checksum(previous / name) for name in ("cases.csv", "trks.csv")
            },
        },
    )
    selected: list[dict[str, Any]] = []
    seen = set(excluded)
    screening = []
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as client:
        for candidate in candidates[:180]:
            patient = f"vitaldb-subject-{candidate['subjectid']}"
            if patient in seen:
                continue
            seen.add(patient)
            folder = root / f"case-{candidate['caseid']}"
            folder.mkdir()
            ids = available[candidate["caseid"]]
            numeric = {name: tid for name, tid in ids.items() if not name.startswith("SNUADC/")}
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(download, client, tid, folder / f"{tid}.csv", duration, budget)
                    for tid in numeric.values()
                ]
                for future in futures:
                    future.result()
            tracks = {
                name: read_track(folder / f"{tid}.csv", duration_s=duration, waveform=False)
                for name, tid in numeric.items()
            }
            cuffs = []
            prior = None
            for ts in tracks["Solar8000/NIBP_MBP"].times:
                parts = [
                    tracks[f"Solar8000/NIBP_{suffix}"].recent(ts, 0.001)
                    for suffix in ("SBP", "DBP", "MBP")
                ]
                if any(part is None for part in parts):
                    continue
                values = tuple(part[1] for part in parts if part is not None)
                if values != prior and 0 < values[1] <= values[2] <= values[0] <= 350:
                    cuffs.append(ts)
                    prior = values
            cursor = 0
            latest: float | None = None
            coverage = 0
            for second in range(900, duration, 5):
                while cursor < len(cuffs) and cuffs[cursor] <= second:
                    latest = cuffs[cursor]
                    cursor += 1
                if (
                    latest is not None
                    and second - latest <= 120
                    and tracks["Solar8000/ART_MBP"].recent(second, 5) is not None
                ):
                    coverage += 1
            accepted = coverage >= 200
            screening.append(
                {
                    "case_id": candidate["caseid"],
                    "patient_id": patient,
                    "reference_windows": coverage,
                    "changed_cuff_observations": len(cuffs),
                    "accepted": accepted,
                }
            )
            print(
                f"M6 COHORT | SCREEN {len(screening)} | reference windows {coverage} | "
                f"selected {len(selected) + int(accepted)}/{count}",
                flush=True,
            )
            if accepted:
                selected.append(
                    {"case_id": candidate["caseid"], "patient_id": patient, "track_ids": ids}
                )
                if len(selected) == count:
                    break
        save_new(root / "screening.json", screening)
        if len(selected) != count:
            raise ValueError("not enough independent reference-available cases; screening retained")
        save_new(
            root / "selection.json",
            {
                "seed": 20261010,
                "count": count,
                "duration_s": duration,
                "cases": selected,
                "source": "https://api.vitaldb.net",
                "labels_reviewed": False,
                "license": "CC BY 4.0",
                "selection_bias": "Reference-available surgical cohort; missing-reference excluded",
            },
        )
        for index, case in enumerate(selected):
            folder = root / f"case-{case['case_id']}"
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [
                    pool.submit(download, client, tid, folder / f"{tid}.csv", duration, budget)
                    for name, tid in case["track_ids"].items()
                    if name.startswith("SNUADC/")
                ]
                for future in futures:
                    future.result()
            manifest = ReplayManifest(
                patient_id=case["patient_id"],
                bed_id="B01",
                context=EpisodeContext(
                    episode_id=f"vitaldb-case-{case['case_id']}", device_id="MON-01", start_ts=0
                ),
                tracks={name: f"{tid}.csv" for name, tid in case["track_ids"].items()},
                duration_s=duration,
            )
            save_new(folder / "manifest.json", manifest.model_dump(mode="json"))
            print(f"M6 COHORT | DOWNLOAD {index + 1}/{count} | VERIFIED", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--duration", type=int, default=7200)
    parser.add_argument("--exclude-selection", type=Path, action="append", default=[])
    parser.add_argument("--max-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--reserve-bytes", type=int, default=30 * 1024**3)
    args = parser.parse_args()
    build(
        args.previous,
        args.root,
        args.count,
        args.duration,
        exclude_selections=tuple(args.exclude_selection),
        max_bytes=args.max_bytes,
        reserve_bytes=args.reserve_bytes,
    )


if __name__ == "__main__":
    main()
