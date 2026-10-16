"""Read-only MQTT/HTTP observer for an operator-started isolated demo.

Stores hashes/metadata, never raw waveform/payload/token contents. Does not publish,
reset, invoke human actions, start a simulator, or establish backend correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from sentinelward.contracts import parse_wire_message
from sentinelward.errors import ContractError
from tools.phase6_acceptance import digest, fresh_output, write_json


def observation(topic: str, payload: bytes, at_ms: int, run_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "received_ts": at_ms,
        "topic": topic,
        "bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    try:
        message = parse_wire_message(topic, payload)
    except ContractError:
        return row | {"validation": "INVALID"}
    body = message.model_dump(mode="json")
    row["validation"] = "VALID"
    for key in (
        "type",
        "bed_id",
        "device_id",
        "ts",
        "seq",
        "model",
        "model_version",
        "window_start",
        "window_s",
        "label",
        "verdict",
        "cmd",
        "run_id",
        "kind",
        "record_id",
    ):
        if key in body:
            row[key] = body[key]
    metadata = body.get("extra", {}) if body.get("type") == "score" else body.get("data", {})
    identity = body.get("run_id", metadata.get("demo_run_id", metadata.get("run_id")))
    valid_identity = isinstance(identity, str) and 0 < len(identity) <= 96
    row["demo_run_id"] = identity if valid_identity else None
    row["identity_metadata_valid"] = valid_identity if identity is not None else None
    row["identity_matches_observed_run"] = identity == run_id if valid_identity else None
    if body.get("type") == "score":
        episode = metadata.get("episode_id")
        row["episode_id"] = episode if isinstance(episode, str) and len(episode) <= 96 else None
        path = metadata.get("assessment_path")
        row["assessment_path"] = (
            path if path in ("unavailable", "cuff_gap_only", "baseline_combined") else None
        )
    # Vitals/verdict wire contracts lack run_id; absence alone does not prove stale input.
    return row


def resource_sample(pids: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {"ts": time.time_ns() // 1_000_000}
    proc = Path("/proc")
    if not proc.is_dir():
        return result | {"status": "NOT RUN", "reason": "Linux procfs unavailable"}
    posix = vars(os)
    result["load_average"] = list(posix["getloadavg"]())
    result["clock_ticks_per_second"] = posix["sysconf"]("SC_CLK_TCK")
    result["cpu_cumulative"] = (proc / "stat").read_text().splitlines()[0]
    memory = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            memory[key + "_kib"] = int(value.split()[0])
    result["memory"] = memory
    processes = {}
    for pid in pids:
        try:
            # The comm field may contain spaces; never read cmdline (which can contain secrets).
            stat = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            processes[str(pid)] = {
                "user_ticks": int(stat[11]),
                "system_ticks": int(stat[12]),
                "start_ticks": int(stat[19]),
                "rss_bytes": int(stat[21]) * posix["sysconf"]("SC_PAGE_SIZE"),
            }
        except (FileNotFoundError, ProcessLookupError):
            processes[str(pid)] = {"status": "NOT RUN", "reason": "process unavailable"}
    return result | {"status": "PASS", "processes": processes}


def validate_config(config: dict[str, Any]) -> None:
    if set(config) != {"v", "run_id", "duration_s", "broker", "probes", "pids"}:
        raise ValueError("unknown or missing observer configuration fields")
    if config["v"] != 1 or not isinstance(config["run_id"], str) or not config["run_id"].strip():
        raise ValueError("invalid observer identity")
    if type(config["duration_s"]) is not int or not 1 <= config["duration_s"] <= 1500:
        raise ValueError("bounded observation duration required")
    broker = config["broker"]
    if set(broker) != {"host", "port", "username", "password_env", "tls", "ca_file"}:
        raise ValueError("invalid observer broker fields")
    if type(broker["tls"]) is not bool or type(broker["port"]) is not int:
        raise ValueError("invalid broker types")
    if not 1 <= broker["port"] <= 65535 or not isinstance(broker["username"], str):
        raise ValueError("invalid broker address/identity")
    if not broker["tls"] and broker["host"] not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("non-TLS MQTT restricted to loopback/tunnel")
    if broker["tls"] and not broker["ca_file"]:
        raise ValueError("explicit trusted CA required")
    if not isinstance(broker["password_env"], str) or not os.getenv(broker["password_env"]):
        raise ValueError("observer password environment variable missing")
    if not isinstance(config["probes"], list) or not isinstance(config["pids"], list):
        raise ValueError("probes/pids must be lists")
    if any(type(pid) is not int or pid <= 0 for pid in config["pids"]):
        raise ValueError("invalid resource process identity")
    for probe in config["probes"]:
        if set(probe) != {"id", "url", "token_env"}:
            raise ValueError("invalid probe fields")
        url = urlparse(probe["url"])
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError("probe URLs cannot embed credentials/query/fragment")
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("HTTP restricted to loopback/tunnel; use HTTPS remotely")
        if probe["token_env"] and not os.getenv(probe["token_env"]):
            raise ValueError("probe token environment variable missing")


def observe(config: dict[str, Any], output: Path) -> dict[str, Any]:
    validate_config(config)
    received: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10000)
    dropped = [0]
    disconnections = [0]
    connected, subscribed = threading.Event(), threading.Event()
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2, client_id="phase6-observer-" + os.urandom(6).hex()
    )
    broker = config["broker"]
    client.username_pw_set(broker["username"], os.environ[broker["password_env"]])
    if broker["tls"]:
        client.tls_set(ca_certs=broker["ca_file"])

    def on_connect(c: Any, u: Any, flags: Any, reason: Any, props: Any) -> None:
        if not reason.is_failure:
            connected.set()
            c.subscribe("ward/#", qos=1)

    def on_subscribe(c: Any, u: Any, mid: Any, reasons: Any, props: Any) -> None:
        if reasons and all(not reason.is_failure for reason in reasons):
            subscribed.set()

    def on_message(c: Any, u: Any, message: Any) -> None:
        row = observation(
            str(message.topic),
            bytes(message.payload),
            time.time_ns() // 1_000_000,
            config["run_id"],
        )
        row["retained"] = bool(message.retain)
        try:
            received.put_nowait(row)
        except queue.Full:
            dropped[0] += 1

    def on_disconnect(c: Any, u: Any, flags: Any, reason: Any, props: Any) -> None:
        disconnections[0] += 1

    def count_row(row: dict[str, Any]) -> None:
        counts[str(row["topic"])] += 1
        if row["validation"] == "INVALID":
            counts["invalid"] += 1
        if row.get("identity_matches_observed_run") is False:
            counts["different_run_identity"] += 1

    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    client.on_disconnect = on_disconnect
    counts: Counter[str] = Counter()
    started = time.monotonic()
    next_probe = 0.0
    client.connect(broker["host"], broker["port"], keepalive=30)
    client.loop_start()
    try:
        if not connected.wait(10) or not subscribed.wait(10):
            raise TimeoutError("observer could not connect/subscribe")
        print("OBSERVER_READY; start the declared run in the simulator/backend now", flush=True)
        started = time.monotonic()
        capture_start_ts = time.time_ns() // 1_000_000
        with (
            (output / "wire.jsonl").open("w", encoding="utf-8") as wire,
            (output / "probes.jsonl").open("w", encoding="utf-8") as probes,
            httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as http,
        ):
            while time.monotonic() - started < config["duration_s"]:
                try:
                    row = received.get(timeout=0.05)
                    wire.write(json.dumps(row, allow_nan=False) + "\n")
                    count_row(row)
                except queue.Empty:
                    pass
                if time.monotonic() >= next_probe:
                    probes.write(json.dumps(resource_sample(config["pids"])) + "\n")
                    for probe in config["probes"]:
                        began = time.monotonic()
                        headers = (
                            {"Authorization": "Bearer " + os.environ[probe["token_env"]]}
                            if (probe["token_env"])
                            else {}
                        )
                        result: dict[str, Any] = {
                            "id": probe["id"],
                            "ts": time.time_ns() // 1_000_000,
                        }
                        try:
                            with http.stream("GET", probe["url"], headers=headers) as response:
                                body = bytearray()
                                for chunk in response.iter_bytes():
                                    body.extend(chunk)
                                    if len(body) > 1_048_576:
                                        raise ValueError("probe response too large")
                                result.update(
                                    status_code=response.status_code,
                                    body_sha256=hashlib.sha256(body).hexdigest(),
                                )
                        except (httpx.HTTPError, ValueError) as exc:
                            result["error_class"] = type(exc).__name__
                        result["elapsed_ms"] = round((time.monotonic() - began) * 1000, 3)
                        probes.write(json.dumps(result) + "\n")
                    wire.flush()
                    probes.flush()
                    next_probe = time.monotonic() + 5
            # Drain messages already received before closing; don't silently omit the tail.
            while not received.empty():
                row = received.get_nowait()
                wire.write(json.dumps(row, allow_nan=False) + "\n")
                count_row(row)
    finally:
        # Ignore our own deliberate final disconnect in the capture-loss count.
        client.on_disconnect = None
        client.disconnect()
        client.loop_stop()
    result = {
        "schema_version": 1,
        "run_id": config["run_id"],
        "status": "FAIL" if dropped[0] or disconnections[0] else "PASS",
        "dropped_by_observer": dropped[0],
        "disconnections_during_capture": disconnections[0],
        "elapsed_s": round(time.monotonic() - started, 3),
        "capture_start_ts": capture_start_ts,
        "capture_end_ts": time.time_ns() // 1_000_000,
        "counts": dict(counts),
        "scope": (
            "Observation completed only; no inference of backend/UI correctness "
            "or source completeness"
        ),
        "files": {name: digest(output / name) for name in ("wire.jsonl", "probes.jsonl")},
    }
    write_json(output / "observation-summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text("utf-8"))
        validate_config(config)
        result = observe(config, fresh_output(args.output))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["status"] == "PASS" else 2)
    except (ValueError, OSError, KeyError, TypeError, TimeoutError):
        print("PHASE6 OBSERVER FAILED; preserve partial files; inspect private configuration")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
