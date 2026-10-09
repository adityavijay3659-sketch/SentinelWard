from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sentinelward.m6 import EpisodeContext, M6State, step
from sentinelward.m6_demo import run_demo
from sentinelward.m6_evaluation import (
    CalibrationArtifact,
    SplitManifest,
    calibrate,
    evaluate,
    read_labelled,
)
from sentinelward.m6_persistence import config_from_artifact
from sentinelward.m6_replay import ReplayManifest, replay_jsonl, replay_vitaldb
from sentinelward.presentation import render_line, wire_output_views


def add_m6_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    m6 = subcommands.add_parser("m6", help="M6 research replay and evaluation")
    commands = m6.add_subparsers(dest="operation", required=True)
    replay = commands.add_parser("replay")
    source = replay.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="local VitalDB track manifest")
    source.add_argument("--input", type=Path, help="locked v1 vitals JSONL")
    replay.add_argument("--context", type=Path, help="episode context for JSONL")
    replay.add_argument("--calibration", type=Path)
    replay.add_argument("--view", choices=("user", "team", "model"), default="team")
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--split", type=Path, required=True)
    calibration.add_argument("--records", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    calibration.add_argument("--stable-fp-limit", type=float, default=0.01)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--artifact", type=Path, required=True)
    evaluation.add_argument("--records", type=Path, required=True)
    evaluation.add_argument("--report", type=Path, required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--report", type=Path)


def save_new(path: Path, value: object) -> None:
    # An existing experiment result is never silently overwritten.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_m6(arguments: argparse.Namespace) -> None:
    def summary(event: str, fact: str, result: str) -> None:
        print(
            render_line(
                timestamp_ms=time.time_ns() // 1_000_000,
                subject="WARD",
                source_event=event,
                key_fact=fact,
                result=result,
            )
        )

    if arguments.operation == "replay":
        if arguments.manifest is not None:
            manifest = ReplayManifest.model_validate_json(arguments.manifest.read_bytes())
            context = manifest.context
            frames = replay_vitaldb(manifest, arguments.manifest.parent)
        else:
            if arguments.context is None:
                raise ValueError("JSONL replay requires --context")
            context = EpisodeContext.model_validate_json(arguments.context.read_bytes())
            frames = replay_jsonl(arguments.input)
        state = M6State(context=context, config=config_from_artifact(arguments.calibration))
        for frame in frames:
            score = step(state, frame)
            if score is not None:
                views = wire_output_views(score)
                print(
                    json.dumps(views.model, separators=(",", ":"), allow_nan=False)
                    if arguments.view == "model"
                    else getattr(views, arguments.view)
                )
    elif arguments.operation == "calibrate":
        split = SplitManifest.model_validate_json(arguments.split.read_bytes())
        artifact = calibrate(
            read_labelled(arguments.records), split, stable_fp_limit=arguments.stable_fp_limit
        )
        save_new(arguments.output, artifact.model_dump(mode="json"))
        summary(
            "M6 VALIDATION",
            f"{artifact.validation_windows} windows; "
            f"threshold={artifact.config.evidence_threshold:.3f}",
            "RESEARCH ONLY",
        )
    elif arguments.operation == "evaluate":
        artifact = CalibrationArtifact.model_validate_json(arguments.artifact.read_bytes())
        # Reserve one ledger per frozen artifact, regardless of report filename.
        ledger = arguments.artifact.with_suffix(arguments.artifact.suffix + ".heldout-used")
        if ledger.exists():
            raise ValueError("held-out evaluation already recorded for this frozen artifact")
        if arguments.report.exists():
            raise FileExistsError("evaluation report already exists")
        report = evaluate(read_labelled(arguments.records), artifact)
        save_new(
            ledger,
            {"artifact_id": artifact.artifact_id, "held_out_sha256": report["held_out_sha256"]},
        )
        save_new(arguments.report, report)
        summary(
            "M6 HELD OUT",
            f"{report['windows']} windows; hypotension false drift="
            f"{report['hypotension_false_drift']}/{report['hypotension_windows']}",
            "REVIEW REQUIRED",
        )
    else:
        report = run_demo()
        if arguments.report is not None:
            save_new(arguments.report, report)
        summary(
            "M6 SYNTHETIC TEST",
            f"{report['bed_count']} beds; hypotension false drift="
            f"{report['hypotension_false_drift']}/{report['hypotension_windows']}",
            "REAL-DATA GATE PENDING",
        )
        outputs = report["outputs"]
        if isinstance(outputs, dict):
            for name in ("level", "hypotension"):
                print(outputs[name]["user"])
