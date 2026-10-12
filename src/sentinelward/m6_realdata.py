"""Bounded public VitalDB download and explicitly unreviewed M6 research experiment.

No clinical ground truth is inferred from an unmodified recording. Perturbation
labels describe operations we performed, not diagnoses or device attacks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from typing import Any

import httpx

from sentinelward.contracts import VitalsMessage
from sentinelward.m6 import EpisodeContext, M6Config, M6State, feature_config_id, step
from sentinelward.m6_cli import save_new
from sentinelward.m6_replay import TRACKS, ReplayManifest, replay_vitaldb
from sentinelward.presentation import wire_output_views

API = "https://api.vitaldb.net"
SEED = 20261009
REQUIRED = (
    *[TRACKS[key] for key in ("abp", "ecg", "ppg", "hr", "sys", "dia", "map")],
    "Solar8000/ART_MBP",
)


class DownloadBudget:
    """Shared conservative byte budget, including retries and reused cached tracks."""

    def __init__(self, root: Path, limit_bytes: int, reserve_bytes: int) -> None:
        if limit_bytes <= 0 or reserve_bytes < 0:
            raise ValueError("invalid download storage budget")
        self.root = root
        self.limit_bytes = limit_bytes
        self.reserve_bytes = reserve_bytes
        self.consumed_bytes = 0
        self._next_disk_check = 0
        self._lock = threading.Lock()

    def consume(self, size: int) -> None:
        with self._lock:
            if size < 0 or self.consumed_bytes + size > self.limit_bytes:
                raise ValueError("cohort download byte budget exhausted; partial data retained")
            if self.consumed_bytes + size >= self._next_disk_check:
                if shutil.disk_usage(self.root).free - size < self.reserve_bytes:
                    raise ValueError("cohort disk reserve reached; partial data retained")
                self._next_disk_check = self.consumed_bytes + size + 1_048_576
            self.consumed_bytes += size


def selection_cases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate local manifest identifiers before using them in artifact paths."""
    cases = plan["cases"]
    if len(cases) < 6 or len(cases) % 3 or len(cases) != plan["count"]:
        raise ValueError("invalid frozen cohort size")
    patients = []
    for case in cases:
        if not re.fullmatch(r"[0-9]+", case["case_id"]) or not re.fullmatch(
            r"vitaldb-subject-[0-9]+", case["patient_id"]
        ):
            raise ValueError("invalid dataset path identifier")
        patients.append(case["patient_id"])
    if len(patients) != len(set(patients)):
        raise ValueError("repeated subjects in frozen cohort")
    return list(cases)


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(
    client: httpx.Client,
    resource: str,
    path: Path,
    duration: int | None = None,
    budget: DownloadBudget | None = None,
) -> dict[str, Any]:
    """Retry bounded read-only requests; atomic promotion and hashes allow safe resume."""
    if not re.fullmatch(r"cases|trks|[a-f0-9]{40}", resource):
        raise ValueError("invalid VitalDB resource")
    receipt = path.with_suffix(".receipt.json")
    if path.exists() and receipt.exists():
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        if previous["sha256"] != checksum(path) or previous["duration_s"] != duration:
            raise ValueError("download cache integrity or duration mismatch")
        if budget is not None:
            budget.consume(path.stat().st_size)
        return dict(previous)
    if path.exists():
        raise FileExistsError("existing track has no verified receipt")
    partial = path.with_suffix(".part")
    for attempt in range(3):
        try:
            with client.stream("GET", f"{API}/{resource}") as response:
                response.raise_for_status()
                if str(response.url) != f"{API}/{resource}":
                    raise ValueError("unexpected data redirect")
                with partial.open("w", encoding="utf-8", newline="") as stream:
                    size = 0
                    interval: float | None = None
                    for count, line in enumerate(response.iter_lines()):
                        line = line.lstrip("\ufeff") if count == 0 else line
                        size += len(line.encode()) + 1
                        if size > 150_000_000:
                            raise ValueError("track exceeds download budget")
                        if budget is not None:
                            budget.consume(len(line.encode()) + 1)
                        stream.write(line + "\n")
                        if duration is not None and count > 0:
                            first = line.split(",", 1)[0]
                            timestamp = float(first or "nan")
                            if count == 2 and 0 < timestamp <= 0.008:
                                interval = timestamp
                            if count > 3:
                                at = (
                                    (count - 1) * interval
                                    if not math.isfinite(timestamp) and interval
                                    else timestamp
                                )
                                if math.isfinite(at) and at >= duration:
                                    break
            partial.replace(path)
            result = {
                "url": f"{API}/{resource}",
                "sha256": checksum(path),
                "bytes": path.stat().st_size,
                "duration_s": duration,
                "subset": duration is not None,
                "downloaded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            save_new(receipt, result)
            return result
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 2:
                raise
            time.sleep(0.5 * 2**attempt)
    raise RuntimeError("unreachable")


def select_cases(
    cases: list[dict[str, str]], tracks: list[dict[str, str]], count: int, duration: int
) -> list[dict[str, Any]]:
    available: dict[str, dict[str, str]] = {}
    for track in tracks:
        if track["tname"] in REQUIRED:
            available.setdefault(track["caseid"], {})[track["tname"]] = track["tid"]
    eligible = [
        case
        for case in cases
        if set(REQUIRED) <= set(available.get(case["caseid"], {}))
        and float(case["caseend"]) >= duration
    ]
    random.Random(SEED).shuffle(eligible)
    selected: list[dict[str, Any]] = []
    subjects: set[str] = set()
    for case in eligible:
        if case["subjectid"] in subjects:
            continue
        subjects.add(case["subjectid"])
        selected.append(
            {
                "case_id": case["caseid"],
                "patient_id": f"vitaldb-subject-{case['subjectid']}",
                "track_ids": available[case["caseid"]],
            }
        )
        if len(selected) == count:
            return selected
    raise ValueError("not enough independent subjects with required tracks")


def fetch(root: Path, count: int, duration: int) -> None:
    if count < 6 or count % 3 or not 1800 <= duration <= 7200:
        raise ValueError("count must be >=6 and divisible by 3; duration must be 1800..7200")
    root.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as client:
        for resource in ("cases", "trks"):
            download(client, resource, root / f"{resource}.csv")
        with (root / "cases.csv").open(encoding="utf-8") as stream:
            cases = list(csv.DictReader(stream))
        with (root / "trks.csv").open(encoding="utf-8") as stream:
            tracks = list(csv.DictReader(stream))
        selection_path = root / "selection.json"
        selection = select_cases(cases, tracks, count, duration)
        plan = {
            "seed": SEED,
            "count": count,
            "duration_s": duration,
            "cases": selection,
            "source": API,
            "license": "CC BY 4.0",
            "labels_reviewed": False,
            "cases_sha256": checksum(root / "cases.csv"),
            "tracks_sha256": checksum(root / "trks.csv"),
        }
        if selection_path.exists():
            if json.loads(selection_path.read_text(encoding="utf-8")) != plan:
                raise ValueError("frozen download selection differs")
        else:
            save_new(selection_path, plan)
        for index, case in enumerate(selection):
            folder = root / f"case-{case['case_id']}"
            folder.mkdir(exist_ok=True)
            names = {name: f"{tid}.csv" for name, tid in case["track_ids"].items()}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [
                    pool.submit(download, client, tid, folder / names[name], duration)
                    for name, tid in case["track_ids"].items()
                ]
                for future in futures:
                    future.result()
            manifest = ReplayManifest(
                patient_id=case["patient_id"],
                bed_id="B01",
                context=EpisodeContext(
                    episode_id=f"vitaldb-case-{case['case_id']}", device_id="MON-01", start_ts=0
                ),
                tracks=names,
                duration_s=duration,
            )
            if not (folder / "manifest.json").exists():
                save_new(folder / "manifest.json", manifest.model_dump(mode="json"))
            print(
                f"VITALDB | DOWNLOAD {index + 1}/{count} | case {case['case_id']} | VERIFIED",
                flush=True,
            )


def perturb(frame: VitalsMessage, variant: str, onset: int) -> VitalsMessage:
    if frame.abp is None or frame.ts < onset:
        return frame
    values = frame.abp
    if variant == "offset_plus_15":
        values = [value + 15 for value in values]
    elif variant == "offset_minus_15":
        values = [value - 15 for value in values]
    elif variant == "ramp_plus_15":
        shift = min(15.0, 15 * (frame.ts - onset) / 300_000)
        values = [value + shift for value in values]
    elif variant == "amplitude_attenuation":
        centre = sum(values) / len(values)
        values = [centre + 0.4 * (value - centre) for value in values]
    return frame.model_copy(update={"abp": values})


def patient_run(
    manifest: ReplayManifest, folder: Path, out: Path, config: M6Config
) -> dict[str, Any]:
    variants = (
        "reference",
        "offset_plus_15",
        "offset_minus_15",
        "ramp_plus_15",
        "amplitude_attenuation",
    )
    states = {name: M6State(context=manifest.context, config=config) for name in variants}
    onset: int | None = None
    fitted = False
    counters: dict[str, Counter[str]] = {name: Counter() for name in variants}
    latency: list[float] = []
    samples: dict[str, Any] = {}
    with (out / f"{manifest.patient_id}.jsonl").open("x", encoding="utf-8") as stream:
        for frame in replay_vitaldb(manifest, folder):
            for name, state in states.items():
                modified = perturb(frame, name, onset) if onset is not None else frame
                started = time.perf_counter()
                score = step(state, modified)
                latency.append((time.perf_counter() - started) * 1000)
                if score is None:
                    continue
                counters[name][score.label] += 1
                # Shared causal warmup; injection starts only after baseline is frozen.
                if name == "reference" and len(state.baseline) >= 179 and not fitted:
                    fitted = True
                    onset = ((frame.ts + 1000 + 4999) // 5000) * 5000
                    save_new(
                        out / f"{manifest.patient_id}-baseline.json", state.model_dump(mode="json")
                    )
                if onset is not None and score.window_start >= onset:
                    row = {
                        "patient_id": manifest.patient_id,
                        "variant": name,
                        "onset_ms": onset,
                        "known_injection": name != "reference",
                        "clinical_labels_reviewed": False,
                        "score": score.model_dump(mode="json"),
                    }
                    stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
                if score.label in {"drift", "emergency_compatible", "insufficient_data"}:
                    views = wire_output_views(score)
                    samples.setdefault(
                        score.label, {"user": views.user, "team": views.team, "model": views.model}
                    )
    ordered = sorted(latency)
    return {
        "patient_id": manifest.patient_id,
        "baseline_fitted": fitted,
        "injection_onset_ms": onset,
        "baseline_windows": len(states["reference"].baseline),
        "label_counts": {name: dict(count) for name, count in counters.items()},
        "step_p95_ms": ordered[int(0.95 * (len(ordered) - 1))],
        "samples": samples,
    }


def metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for variant in sorted({row["variant"] for row in rows}):
        selected = [row for row in rows if row["variant"] == variant]
        positive = [
            row
            for row in selected
            if row["score"]["extra"].get("inputs_sufficient") is True
            and row["score"]["extra"].get("drift_candidate") is True
            and row["score"]["score"] >= threshold
        ]
        sufficient = sum(row["score"]["extra"].get("inputs_sufficient") is True for row in selected)
        events = {row["patient_id"] for row in selected}
        detected = {row["patient_id"] for row in positive}
        delays = {
            patient: min(
                row["score"]["window_start"] + 10_000 - row["onset_ms"]
                for row in positive
                if row["patient_id"] == patient
            )
            for patient in detected
        }
        result[variant] = {
            "windows": len(selected),
            "inputs_sufficient_windows": sufficient,
            "drift_predictions": len(positive),
            "prediction_fraction": len(positive) / len(selected),
            "patients": len(events),
            "patients_with_drift_prediction": len(detected),
            "detection_delay_ms": delays,
            "emergency_compatible_windows": sum(
                row["score"]["label"] == "emergency_compatible" for row in selected
            ),
        }
    return result


def experiment(root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    cases = selection_cases(selection)
    size = len(cases) // 3
    split = {
        name: [case["patient_id"] for case in cases[index * size : (index + 1) * size]]
        for index, name in enumerate(("train", "validation", "test"))
    }
    config = M6Config()
    save_new(
        out / "experiment-plan.json",
        {
            "split": split,
            "config": config.model_dump(mode="json"),
            "feature_config_id": feature_config_id(config),
            "selection_sha256": checksum(root / "selection.json"),
            "code_sha256": checksum(Path(__file__)),
            "reference_fp_limit": 0.01,
            "hypothesis": (
                "Known injected drift is detectable over real recordings "
                "after causal patient warmup"
            ),
            "acceptance": (
                "Useful validation threshold with <=1% unmodified-reference predictions; "
                "clinical labels remain unreviewed"
            ),
            "clinical_approval": False,
            "perturbations_are_synthetic": True,
        },
    )
    reports = []
    threshold: float | None = None
    for phase in ("train", "validation", "test"):
        if phase == "test" and threshold is None:
            # Frozen default, not a secretly relaxed calibration acceptance threshold.
            threshold = config.evidence_threshold
            save_new(
                out / "threshold.json",
                {
                    "threshold": threshold,
                    "status": "validation_failed_default_frozen",
                    "research_only": True,
                },
            )
        for case in cases:
            if case["patient_id"] not in split[phase]:
                continue
            folder = root / f"case-{case['case_id']}"
            manifest = ReplayManifest.model_validate_json((folder / "manifest.json").read_bytes())
            report = patient_run(manifest, folder, out, config)
            report["split"] = phase
            reports.append(report)
            print(
                f"M6 | {phase.upper()} | case {case['case_id']} | "
                f"baseline {report['baseline_windows']}/179",
                flush=True,
            )
        if phase == "validation":
            rows = load_rows(out, split[phase])
            candidates = sorted(
                {
                    config.evidence_threshold,
                    1.0,
                    *[row["score"]["score"] for row in rows if row["score"]["score"] > 0],
                }
            )
            choices = []
            for candidate in candidates:
                facts = metrics(rows, candidate)
                reference = facts.get("reference", {})
                hits = sum(
                    fact["drift_predictions"] for name, fact in facts.items() if name != "reference"
                )
                if reference and reference["prediction_fraction"] <= 0.01 and hits:
                    choices.append((hits, candidate))
            if choices:
                threshold = max(choices)[1]
                save_new(
                    out / "threshold.json",
                    {
                        "threshold": threshold,
                        "status": "controlled_validation_passed",
                        "validation_sha256": hashlib.sha256(
                            json.dumps(rows, sort_keys=True).encode()
                        ).hexdigest(),
                        "research_only": True,
                    },
                )
    assert threshold is not None
    test_rows = load_rows(out, split["test"])
    summary = {
        "source": "VitalDB public surgical recordings",
        "subjects": len(cases),
        "split": split,
        "training": "Causal patient-specific 179-window ridge baselines; no population neural net",
        "baseline_fitted_subjects": sum(report["baseline_fitted"] for report in reports),
        "threshold": json.loads((out / "threshold.json").read_text(encoding="utf-8")),
        "heldout": metrics(test_rows, threshold),
        "patients": reports,
        "clinical_gate": "pending",
        "limitations": [
            "Unmodified reference is not clinically adjudicated stable ground truth",
            "Injected drift labels are synthetic; recordings are real",
            "Surgical data is not ward external validation",
            "Same-patient warmup is causal runtime adaptation, not test-label tuning",
            "M1-M5 teammate models are not trained here",
        ],
        "median_patient_step_p95_ms": median(report["step_p95_ms"] for report in reports),
    }
    save_new(out / "report.json", summary)
    print(
        f"M6 | REAL-DATA RUN | {summary['baseline_fitted_subjects']}/{len(cases)} "
        "baselines fitted | CLINICAL REVIEW PENDING",
        flush=True,
    )


def load_rows(out: Path, patients: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for patient in patients:
        with (out / f"{patient}.jsonl").open(encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream if line.strip())
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("download", "experiment"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--duration", type=int, default=3600)
    args = parser.parse_args()
    if args.operation == "download":
        fetch(args.root, args.count, args.duration)
    elif args.output is None:
        parser.error("experiment requires --output")
    else:
        experiment(args.root, args.output)


if __name__ == "__main__":
    main()
