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
from telegram import Bot

from sentinelward.adapters.alert_publisher import MqttAlertPublisher, MqttOutboxWorker
from sentinelward.adapters.backend import BackendEventClient
from sentinelward.adapters.clinical_backend import ClinicalBackendClient
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.adapters.mqtt import MqttAdapter
from sentinelward.adapters.telegram import (
    TelegramCallbackRouter,
    TelegramIdentityMap,
    TelegramNotifier,
    TelegramPoller,
)
from sentinelward.alert_persistence import PostgresAlertStore
from sentinelward.alerts import AlertCoordinator
from sentinelward.api import create_app
from sentinelward.config import Settings
from sentinelward.contracts import VerdictMessage
from sentinelward.demo_lifecycle import (
    DemoM6Handler,
    PostgresDemoRepository,
    monitor_demo_lifecycle,
)
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.logging_config import configure_logging
from sentinelward.m6_persistence import PostgresM6Handler, config_from_artifact, load_contexts
from sentinelward.persistence import PostgresStore
from sentinelward.phase2_actions import Phase2ActionPort
from sentinelward.phase4_backend import LocalClinicalReference
from sentinelward.phase4_factory import build_phase4
from sentinelward.phase4_reference import create_reference_backend
from sentinelward.ports import ActionPort
from sentinelward.scheduler import DurableAlertScheduler, register_escalation_target
from sentinelward.service import M6Handler, MessageService


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="sentinelward")
    subcommands = value.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate-config")
    database = subcommands.add_parser("db")
    database.add_argument("operation", choices=("upgrade", "init-checkpointer"))
    subcommands.add_parser("serve")
    smoke = subcommands.add_parser("smoke-test")
    smoke.add_argument("--fixture", type=Path)
    from sentinelward.m6_cli import add_m6_parser

    add_m6_parser(subcommands)
    return value


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    arguments = parser().parse_args(argv)
    if arguments.command == "m6":
        from sentinelward.m6_cli import run_m6
        from sentinelward.presentation import sanitize

        try:
            run_m6(arguments)
        except (ValueError, OSError) as exc:
            print(f"M6 | FAILED | {sanitize(exc)[:130]}", file=sys.stderr)
            raise SystemExit(2) from None
        return
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
        asyncio.run(smoke_test(settings, arguments.fixture or default_smoke_fixture()))
        return
    asyncio.run(serve(settings))


def run_migrations(settings: Settings) -> None:
    package_root = Path(__file__).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    packaged_migrations = package_root / "migrations"
    script_location = (
        packaged_migrations if packaged_migrations.is_dir() else source_root / "migrations"
    )
    source_config = source_root / "alembic.ini"
    configuration = Config(source_config if source_config.is_file() else None)
    configuration.set_main_option("script_location", str(script_location))
    sqlalchemy_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    configuration.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(configuration, "head")
    print("DATABASE_UPGRADED")


async def init_checkpointer(database_url: str) -> None:
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        await checkpointer.setup()
    print("CHECKPOINTER_INITIALIZED")


def default_smoke_fixture() -> Path:
    package_fixture = Path(__file__).resolve().parent / "fixtures" / "contract-examples.json"
    if package_fixture.is_file():
        return package_fixture
    source_fixture = Path(__file__).resolve().parents[2] / "fixtures" / "contract-examples.json"
    if source_fixture.is_file():
        return source_fixture
    raise FileNotFoundError("packaged smoke-test fixture is unavailable")


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
    simulated_actions = SimulatedActionPort()
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        alert_coordinator: AlertCoordinator | None = None
        alert_scheduler: DurableAlertScheduler | None = None
        telegram_bot: Bot | None = None
        telegram_poller: TelegramPoller | None = None
        publisher: MqttAlertPublisher | None = None

        action_port: ActionPort
        if settings.external_effect_mode == "live":
            if (
                settings.backend_base_url is None
                or settings.backend_service_token is None
                or settings.telegram_bot_token is None
                or settings.telegram_recipients_file is None
            ):
                raise RuntimeError("live Phase 2 configuration is incomplete")
            backend_token = settings.backend_service_token.get_secret_value()
            clinical_backend = ClinicalBackendClient(
                settings.backend_base_url,
                backend_token,
                timeout_seconds=settings.backend_timeout_seconds,
                max_attempts=settings.backend_max_attempts,
            )
            alert_store = PostgresAlertStore(settings.database_url)
            identities = TelegramIdentityMap.load(settings.telegram_recipients_file)
            telegram_bot = Bot(settings.telegram_bot_token.get_secret_value())
            notifier = TelegramNotifier(
                bot=telegram_bot,
                identities=identities,
                store=alert_store,
            )
            publisher = MqttAlertPublisher(store)
            alert_scheduler = DurableAlertScheduler(settings.database_url)
            alert_coordinator = AlertCoordinator(
                store=alert_store,
                publisher=publisher,
                roster_provider=clinical_backend,
                notifier=notifier,
                waveform_provider=clinical_backend,
                scheduler=alert_scheduler,
                escalation_seconds=settings.alert_escalation_seconds,
            )
            register_escalation_target(alert_coordinator)
            callback_router = TelegramCallbackRouter(
                store=alert_store,
                identities=identities,
                acknowledge=alert_coordinator.acknowledge,
                escalate=alert_coordinator.escalate,
                publish_bedside=publisher.publish_bedside,
            )
            telegram_poller = TelegramPoller(telegram_bot, callback_router)
            action_port = Phase2ActionPort(alert_coordinator, simulated_actions)
        else:
            action_port = simulated_actions

        phase4 = (
            build_phase4(settings.phase4_config_file, settings.database_url)
            if settings.phase4_config_file
            else None
        )
        if phase4 is not None and alert_coordinator is None:
            local_clinical = LocalClinicalReference()
            publisher = MqttAlertPublisher(store)
            alert_scheduler = DurableAlertScheduler(settings.database_url)
            alert_coordinator = AlertCoordinator(
                store=PostgresAlertStore(settings.database_url),
                publisher=publisher,
                roster_provider=local_clinical,
                notifier=local_clinical,
                waveform_provider=local_clinical,
                scheduler=alert_scheduler,
                escalation_seconds=settings.alert_escalation_seconds,
            )
            register_escalation_target(alert_coordinator)
            action_port = Phase2ActionPort(alert_coordinator, simulated_actions)
        if phase4 is not None and alert_coordinator is not None:
            phase4.reset_alerts = alert_coordinator.reset_demo
            phase4.bind_alert_run = alert_coordinator.bind_demo_run
            prior_agent_state = await phase4.snapshot()
            alert_coordinator.bind_demo_run(
                prior_agent_state["run_id"] if prior_agent_state["active"] else None
            )
        engine = AutomationEngine(
            store=store, action_port=action_port, checkpointer=checkpointer, phase4=phase4
        )
        m6_handler: M6Handler | None = None
        demo_handler: DemoM6Handler | None = None
        if settings.m6_enabled and settings.m6_contexts_file is not None:
            contexts = load_contexts(settings.m6_contexts_file)
            m6_config = config_from_artifact(settings.m6_calibration_file)
            if settings.demo_lifecycle_enabled:
                demo_handler = DemoM6Handler(
                    PostgresDemoRepository(settings.database_url), contexts, m6_config
                )
                m6_handler = demo_handler
            else:
                m6_handler = PostgresM6Handler(settings.database_url, contexts, m6_config)
        message_service = MessageService(
            settings,
            store,
            engine,
            health,
            bedside_handler=alert_coordinator,
            m6_handler=m6_handler,
            demo_handler=demo_handler,
            alert_request_handler=alert_coordinator,
            phase4=phase4,
        )
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
            m6_enabled=settings.m6_enabled,
            demo_enabled=settings.demo_lifecycle_enabled,
            phase4_enabled=phase4 is not None,
        )
        health.set("mqtt", await mqtt.start())
        poller_task: asyncio.Task[None] | None = None
        outbox_worker: MqttOutboxWorker | None = None
        outbox_task: asyncio.Task[None] | None = None
        if publisher is not None or settings.m6_enabled or phase4 is not None:
            outbox_worker = MqttOutboxWorker(store, mqtt, health=health)
            outbox_task = asyncio.create_task(outbox_worker.run())
        if alert_scheduler is not None:
            alert_scheduler.start()
        if telegram_bot is not None and telegram_poller is not None:
            await telegram_bot.initialize()
            health.set("telegram", True)
            poller_task = asyncio.create_task(telegram_poller.run())
        application = create_app(
            health,
            alerts=alert_coordinator,
            demo=demo_handler,
            phase4=phase4,
            service_token=(
                settings.backend_service_token.get_secret_value()
                if settings.backend_service_token
                else None
            ),
        )
        if phase4 is not None:
            if settings.backend_service_token is None:
                raise RuntimeError("isolated Phase 4 internal API requires a service token")
            application.mount(
                "/",
                create_reference_backend(
                    phase4,
                    service_token=settings.backend_service_token.get_secret_value(),
                ),
            )
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
        demo_monitor = (
            asyncio.create_task(monitor_demo_lifecycle(demo_handler)) if demo_handler else None
        )

        async def advance_phase4() -> None:
            assert phase4 is not None
            while True:
                await phase4.advance()
                await phase4.flush_timelines()
                await asyncio.sleep(1)

        phase4_monitor = asyncio.create_task(advance_phase4()) if phase4 else None
        try:
            await server.serve()
        finally:
            if phase4_monitor is not None:
                phase4_monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await phase4_monitor
            if demo_monitor is not None:
                demo_monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await demo_monitor
            if outbox_worker is not None:
                await outbox_worker.stop()
            if outbox_task is not None:
                outbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await outbox_task
            if telegram_poller is not None:
                await telegram_poller.stop()
            if poller_task is not None:
                poller_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poller_task
            if telegram_bot is not None:
                await telegram_bot.shutdown()
                health.set("telegram", False)
            if alert_scheduler is not None:
                await alert_scheduler.shutdown()
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
