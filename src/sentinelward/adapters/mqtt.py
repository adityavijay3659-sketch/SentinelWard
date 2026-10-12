from __future__ import annotations

import asyncio
import ssl
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

MessageHandler = Callable[[str, bytes], Coroutine[Any, Any, bool]]


class MqttAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        handler: MessageHandler,
        event_loop: asyncio.AbstractEventLoop,
        keepalive: int = 60,
        username: str | None = None,
        password: str | None = None,
        tls: bool = True,
        ca_file: Path | None = None,
        m6_enabled: bool = False,
        demo_enabled: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._m6_enabled = m6_enabled
        self._demo_enabled = demo_enabled
        self._handler = handler
        self._event_loop = event_loop
        self._connected = asyncio.Event()
        self._client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
            manual_ack=True,
        )
        if username is not None:
            self._client.username_pw_set(username, password)
        if tls:
            context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._client.tls_set_context(context)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    async def start(self) -> bool:
        self._client.connect_async(self._host, self._port, self._keepalive)
        self._client.loop_start()
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10)
        except TimeoutError:
            return False
        return True

    async def stop(self) -> None:
        self._client.disconnect()
        await asyncio.to_thread(self._client.loop_stop)

    async def publish(
        self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None:
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish rejected with code {info.rc}")
        await asyncio.to_thread(info.wait_for_publish, 10)
        if not info.is_published():
            raise TimeoutError("MQTT publish was not acknowledged within 10 seconds")

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del userdata, flags, properties
        if reason_code.is_failure:
            return
        subscriptions = [
            ("ward/request", 1),
            ("ward/bed/+/verdict", 1),
            ("ward/bed/+/bedside", 1),
            ("ward/bed/+/score/M3", 1),
            ("ward/bed/+/score/M5", 1),
        ]
        if self._m6_enabled:
            subscriptions.append(("ward/bed/+/vitals", 0))
        if self._demo_enabled:
            subscriptions.append(("ward/demo/control", 1))
        result, _ = client.subscribe(subscriptions)
        if result == mqtt.MQTT_ERR_SUCCESS:
            self._event_loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del client, userdata, disconnect_flags, reason_code, properties
        self._event_loop.call_soon_threadsafe(self._connected.clear)

    def _on_message(self, client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
        del userdata
        future: Future[bool] = asyncio.run_coroutine_threadsafe(
            self._handler(message.topic, bytes(message.payload)), self._event_loop
        )

        def acknowledge_if_durable(completed: Future[bool]) -> None:
            try:
                should_ack = completed.result()
            except Exception:
                should_ack = False
            if should_ack and message.qos > 0:
                client.ack(message.mid, message.qos)

        future.add_done_callback(acknowledge_if_durable)
