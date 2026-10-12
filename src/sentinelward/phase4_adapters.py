"""Replaceable local implementations; no production model features are imported."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import Field, SecretStr

from sentinelward.contracts import StrictMessage
from sentinelward.phase4_state import Device


class BrokerControl(Protocol):
    async def disabled(self, device: Device) -> bool: ...
    async def disable(self, device: Device) -> None: ...
    async def clean_session(self, device: Device) -> None: ...
    async def enable(self, device: Device) -> None: ...


class ProjectionPort(Protocol):
    async def set_untrusted(self, bed_id: str, latest: dict[str, Any]) -> None: ...
    async def reconnecting(self, bed_id: str) -> None: ...


class WatchPort(Protocol):
    async def replace(self, device_id: str, lease_ids: list[str]) -> None: ...


class BrokerSettings(StrictMessage):
    host: str = "127.0.0.1"
    port: int = Field(default=18883, ge=1, le=65535)
    admin_username: str
    admin_password: SecretStr
    cleanup_username: str
    cleanup_password: SecretStr
    tls_ca: Path | None = None
    timeout_seconds: float = Field(default=5, ge=0.1, le=30)


@dataclass
class MosquittoBrokerControl:
    settings: BrokerSettings

    def _client(self, *, client_id: str, cleanup: bool = False) -> mqtt.Client:
        client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        client.username_pw_set(
            self.settings.cleanup_username if cleanup else self.settings.admin_username,
            (
                self.settings.cleanup_password if cleanup else self.settings.admin_password
            ).get_secret_value(),
        )
        if self.settings.tls_ca is not None:
            client.tls_set(ca_certs=str(self.settings.tls_ca))
        elif self.settings.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("broker control without TLS is restricted to loopback lab")
        return client

    def _command(self, command: str, username: str) -> dict[str, Any]:
        client = self._client(client_id=f"p4-control-{uuid4().hex}")
        done = threading.Event()
        result: dict[str, Any] = {}
        correlation = uuid4().hex

        def connected(
            c: mqtt.Client, userdata: Any, flags: Any, reason: Any, properties: Any
        ) -> None:
            del userdata, flags, properties
            if reason.is_failure:
                result["error"] = "control authentication rejected"
                done.set()
            else:
                c.subscribe("$CONTROL/dynamic-security/v1/response", qos=1)

        def subscribed(
            c: mqtt.Client, userdata: Any, mid: int, reasons: Any, properties: Any
        ) -> None:
            del userdata, mid, reasons, properties
            body = {
                "commands": [
                    {"command": command, "username": username, "correlationData": correlation}
                ]
            }
            c.publish("$CONTROL/dynamic-security/v1", json.dumps(body), qos=1)

        def received(c: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
            del c, userdata
            try:
                for response in json.loads(message.payload).get("responses", []):
                    if response.get("correlationData") == correlation:
                        result.update(response)
                        done.set()
            except (ValueError, TypeError):
                result["error"] = "malformed broker control response"
                done.set()

        client.on_connect, client.on_subscribe, client.on_message = connected, subscribed, received
        try:
            client.connect(self.settings.host, self.settings.port, keepalive=10)
            client.loop_start()
            if not done.wait(self.settings.timeout_seconds):
                raise TimeoutError("broker effect outcome requires reconciliation")
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            return result
        finally:
            client.disconnect()
            client.loop_stop()

    async def disabled(self, device: Device) -> bool:
        result = await asyncio.to_thread(self._command, "getClient", device.username)
        raw = result.get("data", {}).get("client", {})
        if raw.get("clientid") != device.client_id:
            raise ValueError("inventory client binding differs from broker")
        if raw.get("username") != device.username:
            raise ValueError("broker returned a different account")
        # Mosquitto 2.0 serializes disabled only when true.
        if not isinstance(raw.get("disabled", False), bool):
            raise ValueError("broker client disabled state missing")
        return bool(raw.get("disabled", False))

    async def disable(self, device: Device) -> None:
        await asyncio.to_thread(self._command, "disableClient", device.username)
        if not await self.disabled(device):
            raise RuntimeError("broker disable was not confirmed")

    def _clean(self, device: Device) -> None:
        client = self._client(client_id=device.client_id, cleanup=True)
        done = threading.Event()
        errors: list[str] = []

        def connected(
            c: mqtt.Client, userdata: Any, flags: Any, reason: Any, properties: Any
        ) -> None:
            del c, userdata, flags, properties
            if reason.is_failure:
                errors.append("maintenance session authentication rejected")
            done.set()

        client.on_connect = connected
        try:
            client.connect(self.settings.host, self.settings.port, keepalive=10)
            client.loop_start()
            if not done.wait(self.settings.timeout_seconds):
                raise TimeoutError("session cleanup outcome unknown")
            if errors:
                raise RuntimeError(errors[0])
        finally:
            client.disconnect()
            client.loop_stop()

    async def clean_session(self, device: Device) -> None:
        if not await self.disabled(device):
            raise ValueError("session cleanup requires disabled device identity")
        await asyncio.to_thread(self._clean, device)

    async def enable(self, device: Device) -> None:
        await asyncio.to_thread(self._command, "enableClient", device.username)
        if await self.disabled(device):
            raise RuntimeError("broker enable was not confirmed")


@dataclass(frozen=True)
class EvidenceFiles:
    root: Path

    def timeline(
        self, incident_id: str, revision: int, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        directory = (self.root.resolve() / incident_id).resolve()
        if directory.parent != self.root.resolve():
            raise ValueError("invalid timeline path")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"timeline-{revision}.jsonl"
        body = b"".join(
            (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode() for row in rows
        )
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(body)
        actual = path.read_bytes()
        if actual != body:
            raise ValueError("immutable timeline revision mismatch")
        return {
            "kind": "timeline",
            "path": str(path),
            "size_bytes": len(actual),
            "sha256": hashlib.sha256(actual).hexdigest(),
            "verified": True,
            "available": True,
        }

    def freeze(self, incident_id: str, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        base = self.root.resolve()
        directory = (base / incident_id).resolve()
        if directory.parent != base:
            raise ValueError("invalid incident artifact path")
        directory.mkdir(parents=True, exist_ok=True)
        artifacts: list[dict[str, Any]] = []
        for kind in ("vitals", "verdict", "action", "mqtt_observation"):
            rows = [row for row in observations if row["kind"] == kind]
            body = b"".join(
                (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode() for row in rows
            )
            path = directory / f"{kind}.jsonl"
            if not path.exists():
                try:
                    with path.open("xb") as stream:
                        stream.write(body)
                except FileExistsError:
                    pass
            actual = path.read_bytes()
            if actual != body:
                raise ValueError("frozen evidence differs from original snapshot")
            artifacts.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "sha256": hashlib.sha256(actual).hexdigest(),
                    "size_bytes": len(actual),
                    "available": bool(rows),
                    "source": "accepted MQTT message transcript; not PCAP",
                    "verified": True,
                }
            )
        return artifacts

    def verify(self, artifacts: list[dict[str, Any]]) -> bool:
        base = self.root.resolve()
        for artifact in artifacts:
            path = Path(artifact["path"]).resolve()
            if not path.is_relative_to(base):
                return False
            try:
                body = path.read_bytes()
            except OSError:
                return False
            if (
                len(body) != artifact["size_bytes"]
                or hashlib.sha256(body).hexdigest() != artifact["sha256"]
            ):
                return False
        return True
