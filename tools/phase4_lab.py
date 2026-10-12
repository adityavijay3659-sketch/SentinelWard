"""Provision a user-owned portable Mosquitto lab; never install a system service."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path
from typing import Any


def acl(kind: str, topic: str) -> dict[str, Any]:
    return {"acltype": kind, "topic": topic, "allow": True}


def configure(root: Path, broker_bin: Path, port: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    credentials = {
        name: secrets.token_urlsafe(24)
        for name in (
            "p4-admin",
            "p4-cleanup",
            "p4-backend",
            "p4-observer",
            "p4-decision",
            "MON-01",
            "MON-02",
            "MON-03",
        )
    }
    roles: list[dict[str, Any]] = []
    clients: list[dict[str, Any]] = []
    for name, password in credentials.items():
        salt = secrets.token_bytes(12)
        client: dict[str, Any] = {
            "username": name,
            "password": base64.b64encode(
                hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 101)
            ).decode(),
            "salt": base64.b64encode(salt).decode(),
            "iterations": 101,
            "roles": [{"rolename": name}],
        }
        allowed: list[dict[str, Any]] = []
        if name == "p4-admin":
            allowed = [
                acl(kind, "$CONTROL/dynamic-security/#")
                for kind in ("publishClientSend", "publishClientReceive", "subscribePattern")
            ]
        elif name == "p4-backend":
            allowed = [
                acl("publishClientSend", topic) for topic in ("ward/demo/control", "ward/request")
            ]
        elif name == "p4-observer":
            allowed = [
                acl("publishClientReceive", "ward/#"),
                acl("subscribePattern", "ward/#"),
                acl("publishClientSend", "ward/action"),
                acl("publishClientSend", "ward/record"),
                acl("publishClientSend", "ward/alert"),
                acl("publishClientSend", "ward/bed/+/score/M6"),
                acl("publishClientSend", "lab/session/test"),
            ]
        elif name == "p4-decision":
            allowed = [acl("publishClientSend", "ward/bed/+/verdict")]
        elif name.startswith("MON-"):
            bed = "B" + name[-2:]
            client["clientid"] = name
            allowed = [
                acl("publishClientSend", f"ward/bed/{bed}/vitals"),
                acl("publishClientReceive", "lab/session/test"),
                acl("subscribePattern", "lab/session/test"),
            ]
        clients.append(client)
        roles.append({"rolename": name, "acls": allowed})
    security = {
        "clients": clients,
        "roles": roles,
        "groups": [],
        "defaultACLAccess": {
            "publishClientSend": False,
            "publishClientReceive": False,
            "subscribe": False,
            "unsubscribe": False,
        },
    }
    (root / "dynamic-security.json").write_text(json.dumps(security), encoding="utf-8")
    (root / "credentials.json").write_text(json.dumps(credentials), encoding="utf-8")
    suffix = ".dll" if os.name == "nt" else ".so"
    plugin = broker_bin / ("mosquitto_dynamic_security" + suffix)
    config = root / "mosquitto.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous false\n"
        f"plugin {plugin.as_posix()}\n"
        f"plugin_opt_config_file {(root / 'dynamic-security.json').as_posix()}\n"
        f"persistence true\npersistence_location {root.as_posix()}/\n"
        "log_type error\nlog_type warning\nlog_type notice\n",
        encoding="utf-8",
    )
    runtime = {
        "v": 1,
        "isolated_lab": True,
        "inventory": [
            {
                "device_id": f"MON-{i:02}",
                "bed_id": f"B{i:02}",
                "username": f"MON-{i:02}",
                "client_id": f"MON-{i:02}",
                "model": "LabMon-A" if i < 3 else "LabMon-B",
                "firmware": "fixture-1",
                "lab_owned": True,
            }
            for i in range(1, 4)
        ],
        "broker": {
            "host": "127.0.0.1",
            "port": port,
            "admin_username": "p4-admin",
            "admin_password": credentials["p4-admin"],
            "cleanup_username": "p4-cleanup",
            "cleanup_password": credentials["p4-cleanup"],
        },
        "evidence_root": str(root / "evidence"),
        "containment_policy": {
            "version": "fixture-only-1",
            "threshold": 0.8,
            "comparator": ">=",
            "approved": False,
        },
    }
    runtime_path = root / "runtime.json"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--broker-bin", type=Path)
    parser.add_argument("--port", type=int, default=18883)
    args = parser.parse_args()
    if args.operation == "stop":
        pid_path = args.root / "broker.pid"
        if not pid_path.exists():
            print("PHASE4_LAB_ALREADY_STOPPED")
            return
        pid = int(pid_path.read_text())
        # Stop only the broker process started by this lab.
        if os.name == "nt":
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
            expected_file = args.root / "broker.executable"
            expected = (
                Path(expected_file.read_text())
                if expected_file.exists()
                else args.root.parent / "mosquitto" / "mosquitto.exe"
            )
            if inspected and Path(inspected).resolve() != expected.resolve():
                raise RuntimeError("process receipt no longer identifies this lab broker")
            if inspected:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True
                )
        else:
            import signal

            os.kill(pid, signal.SIGTERM)
        pid_path.unlink()
        print("PHASE4_LAB_STOPPED")
        return
    if args.broker_bin is None:
        parser.error("--broker-bin is required for start")
    if (args.root / "broker.pid").exists():
        parser.error("lab already has a process receipt; inspect/stop it before start")
    config = configure(args.root, args.broker_bin, args.port)
    exe = args.broker_bin / ("mosquitto.exe" if os.name == "nt" else "mosquitto")
    with (args.root / "broker.log").open("ab") as log:
        process = subprocess.Popen(
            [str(exe), "-c", str(config)],
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    (args.root / "broker.pid").write_text(str(process.pid))
    (args.root / "broker.executable").write_text(str(exe.resolve()))
    print("PHASE4_LAB_STARTED; credentials stay outside repository")


if __name__ == "__main__":
    main()
