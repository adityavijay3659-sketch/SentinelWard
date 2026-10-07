from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import uvicorn
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from sentinelward.adapters.backend import BackendEventClient
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.adapters.mqtt import MqttAdapter
from sentinelward.api import create_app
from sentinelward.config import Settings
from sentinelward.contracts import VerdictMessage
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.logging_config import configure_logging
from sentinelward.persistence import PostgresStore
from sentinelward.service import MessageService


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="sentinelward")
    subcommands = value.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate-config")
    database = subcommands.add_parser("db")
    database.add_argument("operation", choices=("upgrade", "init-checkpointer"))
    subcommands.add_parser("serve")
    smoke = subcommands.add_parser("smoke-test")
    smoke.add_argument("--fixture", default="fixtures/contract-examples.json", type=Path)
    return value


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    arguments = parser().parse_args(argv)
    settings = Settings()
    settings.validate_files()
    configure_logging(settings.log_level)
    if arguments.command == "validate-config":
        print("CONFIG_VALID")
        return
    if arguments.command == "db":
        if arguments.operation == "upgrade":
            run_migrations(settings)
        else:
            asyncio.run(init_checkpointer(settings.database_url))
        return
    if arguments.command == "smoke-test":
        asyncio.run(smoke_test(settings, arguments.fixture))
        return
    asyncio.run(serve(settings))


def run_migrations(settings: Settings) -> None:
    root = Path(__file__).resolve().parents[2]
    configuration = Config(root / "alembic.ini")
    configuration.set_main_option("script_location", str(root / "migrations"))
    sqlalchemy_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    configuration.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(configuration, "head")
    print("DATABASE_UPGRADED")


async def init_checkpointer(database_url: str) -> None:
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        await checkpointer.setup()
    print("CHECKPOINTER_INITIALIZED")


async def smoke_test(settings: Settings, fixture_path: Path) -> None:
    fixture: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    source = VerdictMessage.model_validate(fixture["verdicts"][1])
    now_ms = time.time_ns() // 1_000_000
    verdict = source.model_copy(update={"ts": now_ms, "window_start": now_ms - 5_000})
    store = PostgresStore(settings.database_url)
    action_port = SimulatedActionPort()
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        engine = AutomationEngine(store=store, action_port=action_port, checkpointer=checkpointer)
        service = MessageService(settings, store, engine, HealthRegistry())
        payload = verdict.model_dump_json().encode()
        await service.handle(f"ward/bed/{verdict.bed_id}/verdict", payload)
        await service.handle(f"ward/bed/{verdict.bed_id}/verdict", payload)
    if len(action_port.calls) != 1:
        raise RuntimeError(
            f"smoke test expected one external action, observed {len(action_port.calls)}"
        )
    print("SMOKE_TEST_PASSED")


async def serve(settings: Settings) -> None:
    health = HealthRegistry()
    store = PostgresStore(settings.database_url)
    health.set("postgres", await store.ping())
    backend = (
        BackendEventClient(
            settings.backend_base_url,
            settings.backend_service_token.get_secret_value(),
            timeout_seconds=settings.backend_timeout_seconds,
            max_attempts=settings.backend_max_attempts,
        )
        if settings.backend_base_url and settings.backend_service_token
        else None
    )
    health.set("backend", await backend.health() if backend else False)
    action_port = SimulatedActionPort()
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        engine = AutomationEngine(store=store, action_port=action_port, checkpointer=checkpointer)
        message_service = MessageService(settings, store, engine, health)
        loop = asyncio.get_running_loop()
        mqtt = MqttAdapter(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            client_id=settings.mqtt_client_id,
            handler=message_service.handle,
            event_loop=loop,
            keepalive=settings.mqtt_keepalive_seconds,
            username=settings.mqtt_username,
            password=settings.mqtt_password.get_secret_value() if settings.mqtt_password else None,
            tls=settings.mqtt_tls,
            ca_file=settings.mqtt_ca_file,
        )
        health.set("mqtt", await mqtt.start())
        application = create_app(health)
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host=settings.http_host,
                port=settings.http_port,
                log_config=None,
            )
        )
        monitor = asyncio.create_task(
            monitor_dependencies(health=health, store=store, mqtt=mqtt, backend=backend)
        )
        try:
            await server.serve()
        finally:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
            health.set("mqtt", False)
            await mqtt.stop()


async def monitor_dependencies(
    *,
    health: HealthRegistry,
    store: PostgresStore,
    mqtt: MqttAdapter,
    backend: BackendEventClient | None,
) -> None:
    while True:
        health.set("postgres", await store.ping())
        health.set("mqtt", mqtt.connected)
        health.set("backend", await backend.health() if backend else False)
        await asyncio.sleep(5)
