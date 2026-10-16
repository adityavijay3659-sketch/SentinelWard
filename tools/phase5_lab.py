"""Owned loopback Granite harness; model/credentials/logs stay outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt = root / "granite-process.json"
    if args.operation == "stop":
        if not receipt.exists():
            print("PHASE5_GRANITE_ALREADY_STOPPED")
            return
        metadata = json.loads(receipt.read_text())
        pid = int(metadata["pid"])
        inspected = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Path",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if inspected and Path(inspected).resolve() != Path(metadata["binary"]).resolve():
            raise RuntimeError("process identity no longer belongs to this harness")
        if inspected:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=True)
        receipt.unlink()
        print("PHASE5_GRANITE_STOPPED")
        return
    if args.binary is None or args.model is None:
        parser.error("start requires explicit binary and model")
    if receipt.exists():
        parser.error("existing process receipt; inspect/stop before starting")
    with args.model.open("rb") as stream:
        model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    expected = "ca71c0faaea5647c6f34bb55d8ae9516e94828e0065cdbbf4680348be2bbbfd3"
    if model_hash != expected:
        raise ValueError("model differs from the approved local Granite artifact")
    api_key = secrets.token_urlsafe(32)
    config = {
        "v": 1,
        "isolated_lab": True,
        "staff": {
            "version": "lab-phase5-1",
            "nurses": ["staff:priya", "staff:ravi"],
            "charge_nurse": "staff:charge",
            "valid_until": 253_402_300_799_999,
            "schedule": {"timezone": "Asia/Kolkata", "starts": []},
        },
        "staff_credentials": [
            {"token": secrets.token_urlsafe(32), "principal": {"by": f"staff:{role}", "role": role}}
            for role in ("it", "nurse", "doctor")
        ],
        "report_profile": {
            "organisation": "TessNova fictional demo",
            "sector": "Health",
            "critical_to_mission": True,
        },
        "writer": {
            "base_url": f"http://127.0.0.1:{args.port}",
            "model": "granite-phase5",
            "model_file": str(args.model.resolve()),
            "model_sha256": model_hash,
            "build": "11433-50569eb87",
            "api_key": api_key,
        },
    }
    (root / "runtime.json").write_text(json.dumps(config, indent=2))
    with (root / "granite-server.log").open("ab") as log:
        process = subprocess.Popen(
            [
                str(args.binary.resolve()),
                "--model",
                str(args.model.resolve()),
                "--alias",
                "granite-phase5",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--api-key",
                api_key,
                "--ctx-size",
                "4096",
                "--parallel",
                "1",
                "--threads",
                "2",
                "--jinja",
                "--chat-template-kwargs",
                '{"thinking":false,"enable_thinking":false}',
            ],
            cwd=args.binary.parent,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    receipt.write_text(
        json.dumps(
            {"pid": process.pid, "binary": str(args.binary.resolve()), "model_sha256": model_hash}
        )
    )
    print("PHASE5_GRANITE_STARTED; private config outside Git")


if __name__ == "__main__":
    main()
