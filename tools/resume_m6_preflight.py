"""Checkpoint each patient so a read-only M6 coverage audit survives interruption."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from sentinelward.m6 import MODEL_VERSION
from sentinelward.m6_quality import preflight
from sentinelward.m6_realdata import checksum, selection_cases
from sentinelward.m6_replay import ReplayManifest


def result_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_atomic_new(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError("existing audit artifact is preserved")
    partial = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    with partial.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Windows rename refuses to overwrite an existing target. Partial files
    # from interrupted writes are retained and never mistaken for checkpoints.
    partial.rename(path)


def fingerprint(path: Path) -> dict[str, str]:
    manifest = ReplayManifest.model_validate_json(path.read_bytes())
    result = {"manifest.json": checksum(path)}
    folder = path.parent.resolve()
    for name in manifest.tracks.values():
        track = (folder / name).resolve()
        if not track.is_relative_to(folder):
            raise ValueError("track escapes case directory")
        result[name] = checksum(track)
        receipt = track.with_suffix(".receipt.json")
        if receipt.exists():
            result[receipt.name] = checksum(receipt)
    return result


def resume_preflight(root: Path, checkpoints: Path, report_path: Path) -> dict[str, Any]:
    selection = root / "selection.json"
    cases = selection_cases(json.loads(selection.read_text(encoding="utf-8")))
    source = Path(__file__).resolve().parents[1] / "src/sentinelward"
    plan = {
        "model_version": MODEL_VERSION,
        "selection_sha256": checksum(selection),
        "root": str(root.resolve()),
        "runner_sha256": checksum(Path(__file__)),
        "environment": {"python": sys.version, "pydantic": importlib.metadata.version("pydantic")},
        "source_hashes": {
            name: checksum(source / name)
            for name in ("m6.py", "m6_replay.py", "m6_quality.py", "contracts.py")
        },
        "patients": [case["patient_id"] for case in cases],
    }
    if checkpoints.exists():
        saved = json.loads((checkpoints / "plan.json").read_text(encoding="utf-8"))
        if saved != plan:
            raise ValueError("checkpoint source/cohort changed; use a new audit directory")
    else:
        checkpoints.mkdir(parents=True, exist_ok=False)
        save_atomic_new(checkpoints / "plan.json", plan)
    results = []
    for case in cases:
        path = root / f"case-{case['case_id']}" / "manifest.json"
        checkpoint = checkpoints / f"{case['patient_id']}.json"
        inputs = fingerprint(path)
        if checkpoint.exists():
            saved_case = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved_case["input_sha256"] != inputs:
                raise ValueError("cached patient data changed; checkpoint cannot be reused")
            result = saved_case["preflight"]
            if result_hash(result) != saved_case["result_sha256"]:
                raise ValueError("cached patient result integrity mismatch")
        else:
            result = preflight(manifest=path)
            if result["source_hashes"] != plan["source_hashes"] or fingerprint(path) != inputs:
                raise ValueError("source or data changed during patient audit")
            save_atomic_new(
                checkpoint,
                {"input_sha256": inputs, "preflight": result, "result_sha256": result_hash(result)},
            )
        if (
            result["model_version"] != MODEL_VERSION
            or result["cases"][0]["patient_id"] != case["patient_id"]
        ):
            raise ValueError("checkpoint patient/version mismatch")
        results.append(result)
        print(
            f"M6 PREFLIGHT | {len(results)}/{len(cases)} patients checkpointed | RESEARCH ONLY",
            flush=True,
        )
    combined = dict(results[0])
    combined["cases"] = [result["cases"][0] for result in results]
    combined["patients"] = len(cases)
    combined["baseline_ready_patients"] = sum(case["baseline_ready"] for case in combined["cases"])
    combined["checkpoint_plan_sha256"] = checksum(checkpoints / "plan.json")
    if report_path.exists():
        if json.loads(report_path.read_text(encoding="utf-8")) != combined:
            raise ValueError("existing combined report differs; preserved for review")
    else:
        save_atomic_new(report_path, combined)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = resume_preflight(args.root, args.checkpoints, args.report)
    print(
        f"M6 PREFLIGHT | COMPLETE | baseline ready "
        f"{result['baseline_ready_patients']}/{result['patients']} | RESEARCH ONLY"
    )


if __name__ == "__main__":
    main()
