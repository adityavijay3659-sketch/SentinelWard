"""Real portable Mosquitto tests; set SENTINEL_TEST_PHASE4_CONFIG explicitly."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.enums import CallbackAPIVersion

from sentinelward.phase4_adapters import MosquittoBrokerControl
from sentinelward.phase4_factory import Phase4Configuration

CONFIG = os.getenv("SENTINEL_TEST_PHASE4_CONFIG")


def connect_device(
    configuration: Phase4Configuration, password: str, clean: bool
) -> tuple[mqtt.Client, bool, threading.Event, list[bytes]]:
    event = threading.Event()
    disconnected = threading.Event()
    present: list[bool] = []
    errors: list[str] = []
    messages: list[bytes] = []
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="MON-01", clean_session=clean)
    client.username_pw_set("MON-01", password)
    client.on_message = lambda c, u, message: messages.append(message.payload)

    def connected(c: mqtt.Client, user: Any, flags: Any, reason: Any, properties: Any) -> None:
        del c, user, properties
        present.append(bool(flags.session_present))
        if reason.is_failure:
            errors.append(str(reason))
        event.set()

    def closed(c: mqtt.Client, user: Any, flags: Any, reason: Any, properties: Any) -> None:
        del c, user, flags, reason, properties
        disconnected.set()

    client.on_connect, client.on_disconnect = connected, closed
    client.connect(configuration.broker.host, configuration.broker.port)
    client.loop_start()
    if not event.wait(5) or errors:
        client.disconnect()
        client.loop_stop()
        raise PermissionError("broker connection denied")
    return client, present[0], disconnected, messages


@pytest.mark.integration
@pytest.mark.skipif(CONFIG is None, reason="isolated Phase 4 broker not configured")
@pytest.mark.asyncio
async def test_real_disable_cleanup_and_authorized_reconnect() -> None:
    assert CONFIG is not None
    path = Path(CONFIG)
    configuration = Phase4Configuration.model_validate(json.loads(path.read_text()))
    credentials = json.loads((path.parent / "credentials.json").read_text())
    broker = MosquittoBrokerControl(configuration.broker)
    device = configuration.inventory[0]
    if await broker.disabled(device):
        await broker.enable(device)
    client, _, disconnected, messages = await asyncio.to_thread(
        connect_device, configuration, credentials["MON-01"], False
    )
    subscribed = threading.Event()
    client.on_subscribe = lambda *args: subscribed.set()
    client.subscribe("lab/session/test", qos=1)
    assert await asyncio.to_thread(subscribed.wait, 5)
    # Leave a real QoS 1 delivery unacknowledged in the persistent session.
    client.manual_ack_set(True)
    sender = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="verify-" + uuid4().hex)
    sender.username_pw_set("p4-observer", credentials["p4-observer"])
    sender.connect(configuration.broker.host, configuration.broker.port)
    sender.loop_start()
    published = sender.publish("lab/session/test", "old unacknowledged delivery", qos=1)
    await asyncio.to_thread(published.wait_for_publish, 5)
    for _ in range(50):
        if messages:
            break
        await asyncio.sleep(0.02)
    assert messages == [b"old unacknowledged delivery"]
    await broker.disable(device)
    assert await asyncio.to_thread(disconnected.wait, 5)
    client.loop_stop()
    assert await broker.disabled(device)
    with pytest.raises(PermissionError):
        await asyncio.to_thread(connect_device, configuration, credentials["MON-01"], False)
    # Persistent session still exists after disable; cleaning must remove it.
    await broker.clean_session(device)
    assert await broker.disabled(device)
    await broker.enable(device)
    client, session_present, _, messages = await asyncio.to_thread(
        connect_device, configuration, credentials["MON-01"], False
    )
    assert session_present is False
    received = threading.Event()
    client.on_message = lambda *args: received.set()
    published = sender.publish("lab/session/test", "must not use old subscription", qos=1)
    await asyncio.to_thread(published.wait_for_publish, 5)
    assert not await asyncio.to_thread(received.wait, 0.3)
    assert messages == []  # Neither the old delivery nor its subscription survived.
    client.disconnect()
    client.loop_stop()
    sender.disconnect()
    sender.loop_stop()
