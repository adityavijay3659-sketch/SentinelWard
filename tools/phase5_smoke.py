"""Start the actual isolated service, probe protected routes, stop only that child."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase4", type=Path, required=True)
    parser.add_argument("--phase5", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=18095)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    broker = json.loads(args.phase4.read_text())["broker"]
    credentials = json.loads((args.phase4.parent / "credentials.json").read_text())
    phase5 = json.loads(args.phase5.read_text())
    context = args.root / "contexts.json"
    context.write_text(
        json.dumps(
            {
                row["bed_id"]: {
                    "episode_id": "template-" + row["bed_id"],
                    "device_id": row["device_id"],
                    "start_ts": 0,
                }
                for row in json.loads(args.phase4.read_text())["inventory"]
            }
        )
    )
    token = secrets.token_urlsafe(32)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("SENTINEL_")}
    environment.update(
        {
            "SENTINEL_ENVIRONMENT": "test",
            "SENTINEL_DATABASE_URL": args.database,
            "SENTINEL_MQTT_HOST": broker["host"],
            "SENTINEL_MQTT_PORT": str(broker["port"]),
            "SENTINEL_MQTT_TLS": "false",
            "SENTINEL_MQTT_USERNAME": "p4-observer",
            "SENTINEL_MQTT_PASSWORD": credentials["p4-observer"],
            "SENTINEL_MQTT_CLIENT_ID": "phase5-startup-smoke",
            "SENTINEL_BACKEND_SERVICE_TOKEN": token,
            "SENTINEL_M6_ENABLED": "true",
            "SENTINEL_M6_CONTEXTS_FILE": str(context.resolve()),
            "SENTINEL_DEMO_LIFECYCLE_ENABLED": "true",
            "SENTINEL_PHASE4_CONFIG_FILE": str(args.phase4.resolve()),
            "SENTINEL_PHASE5_CONFIG_FILE": str(args.phase5.resolve()),
            "SENTINEL_HTTP_HOST": "127.0.0.1",
            "SENTINEL_HTTP_PORT": str(args.port),
            "SENTINEL_EXTERNAL_EFFECT_MODE": "simulate",
            "LANGGRAPH_STRICT_MSGPACK": "true",
        }
    )
    # An empty working directory avoids inheriting a developer's unrelated .env.
    subprocess.run(
        [sys.executable, "-m", "sentinelward", "validate-config"],
        env=environment,
        cwd=args.root,
        check=True,
        capture_output=True,
    )
    with (args.root / "service.log").open("ab") as log:
        child = subprocess.Popen(
            [sys.executable, "-m", "sentinelward", "serve"],
            env=environment,
            cwd=args.root,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}", timeout=5, trust_env=False
        ) as client:
            deadline = time.monotonic() + 90
            while True:
                if child.poll() is not None:
                    raise RuntimeError("service exited; inspect private service.log")
                try:
                    response = client.get("/health/live")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("service startup deadline")
                time.sleep(0.25)
            assert client.get("/internal/v1/phase5/status").status_code == 401
            status = client.get(
                "/internal/v1/phase5/status", headers={"Authorization": "Bearer " + token}
            )
            assert status.status_code == 200
            nurse = next(
                c for c in phase5["staff_credentials"] if c["principal"]["role"] == "nurse"
            )
            assert (
                client.get(
                    "/api/briefing", headers={"Authorization": "Bearer " + nurse["token"]}
                ).status_code
                == 200
            )
            result = {
                "service_started": True,
                "internal_unauthenticated": 401,
                "internal_authenticated": 200,
                "nurse_briefing_read": 200,
                "scope": "Actual CLI and local HTTP only; deployed integration unverified",
            }
            (args.root / "startup-result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
    finally:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


if __name__ == "__main__":
    main()
