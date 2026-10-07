from __future__ import annotations

import asyncio
from types import SimpleNamespace

import paho.mqtt.client as mqtt
import pytest

from sentinelward.adapters.mqtt import MqttAdapter


class SuccessfulReason:
    is_failure = False


class FakePublishInfo:
    rc = mqtt.MQTT_ERR_SUCCESS

    def __init__(self) -> None:
        self.waited = False

    def wait_for_publish(self, timeout: float) -> None:
        assert timeout == 10
        self.waited = True

    def is_published(self) -> bool:
        return self.waited


class FakeMqttClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.subscriptions: list[tuple[str, int]] = []
        self.acknowledged: list[tuple[int, int]] = []
        self.connected = False
        self.publish_info = FakePublishInfo()

    def username_pw_set(self, username: str, password: str | None) -> None:
        self.credentials = (username, password)

    def reconnect_delay_set(self, min_delay: int, max_delay: int) -> None:
        self.reconnect_delays = (min_delay, max_delay)

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        self.connection = (host, port, keepalive)

    def loop_start(self) -> None:
        self.connected = True
        assert self.on_connect is not None
        self.on_connect(self, None, None, SuccessfulReason(), None)

    def loop_stop(self) -> None:
        self.connected = False

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def subscribe(self, subscriptions: list[tuple[str, int]]) -> tuple[int, int]:
        self.subscriptions = subscriptions
        return mqtt.MQTT_ERR_SUCCESS, 1

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> FakePublishInfo:
        self.published = (topic, payload, qos, retain)
        return self.publish_info

    def ack(self, message_id: int, qos: int) -> None:
        self.acknowledged.append((message_id, qos))


@pytest.mark.asyncio
async def test_mqtt_acknowledges_only_after_durable_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[FakeMqttClient] = []

    def factory(*args: object, **kwargs: object) -> FakeMqttClient:
        client = FakeMqttClient(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("sentinelward.adapters.mqtt.mqtt.Client", factory)
    durable = True
    handled = asyncio.Event()

    async def handler(topic: str, payload: bytes) -> bool:
        assert topic == "ward/bed/B01/verdict"
        assert payload == b"{}"
        handled.set()
        return durable

    adapter = MqttAdapter(
        host="broker.test",
        port=1883,
        client_id="sentinelward-test",
        handler=handler,
        event_loop=asyncio.get_running_loop(),
        tls=False,
    )
    assert await adapter.start() is True
    client = clients[0]
    assert client.kwargs["clean_session"] is False
    assert client.kwargs["manual_ack"] is True
    assert ("ward/bed/+/verdict", 1) in client.subscriptions

    message = SimpleNamespace(topic="ward/bed/B01/verdict", payload=b"{}", qos=1, mid=42)
    adapter._on_message(client, None, message)
    await asyncio.wait_for(handled.wait(), timeout=1)
    await asyncio.sleep(0)
    assert client.acknowledged == [(42, 1)]

    durable = False
    handled.clear()
    message.mid = 43
    adapter._on_message(client, None, message)
    await asyncio.wait_for(handled.wait(), timeout=1)
    await asyncio.sleep(0)
    assert client.acknowledged == [(42, 1)]

    await adapter.publish("ward/action", b"{}")
    assert client.published == ("ward/action", b"{}", 1, False)
    assert client.publish_info.waited is True
    await adapter.stop()
