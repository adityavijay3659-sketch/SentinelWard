"""Read-only connectivity audit. Never send clinical alerts or print credentials."""

from __future__ import annotations

import argparse
import importlib.metadata
import socket
from pathlib import Path
from typing import Any

import httpx
import psycopg

from sentinelward.config import Settings
from sentinelward.m6_cli import save_new

DEPENDENCIES = (
    "langgraph",
    "langgraph-checkpoint-postgres",
    "psycopg",
    "paho-mqtt",
    "apscheduler",
    "fastapi",
    "httpx",
    "python-telegram-bot",
    "pydantic",
    "sqlalchemy",
)


def audit(settings: Settings, client: httpx.Client) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "profile": settings.environment,
        "external_effect_mode": settings.external_effect_mode,
        "dependencies": {name: importlib.metadata.version(name) for name in DEPENDENCIES},
        "clinical_messages_sent": 0,
    }
    try:
        settings.validate_files()
        facts["configured_files"] = "valid"
    except (ValueError, OSError):
        facts["configured_files"] = "invalid_or_missing"
    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as connection:
            row = connection.execute("SELECT 1, current_setting('server_version')").fetchone()
            facts["postgres"] = {"status": "connected", "server_version": row[1] if row else None}
    except psycopg.Error:
        facts["postgres"] = {"status": "unreachable_or_auth_failed"}
    try:
        with socket.create_connection((settings.mqtt_host, settings.mqtt_port), timeout=2):
            pass
        transport = "tcp_connected_protocol_not_verified"
    except OSError:
        transport = "tcp_unreachable"
    facts["mqtt"] = {
        "status": transport,
        "tls_required": settings.mqtt_tls,
        "ca_configured": settings.mqtt_ca_file is not None,
        "credentials_configured": bool(settings.mqtt_username and settings.mqtt_password),
        "authenticated_publish_subscribe": "pending",
    }
    if not settings.backend_base_url or settings.backend_service_token is None:
        facts["backend"] = {"status": "not_configured", "authenticated_health": "pending"}
    else:
        try:
            response = client.get(
                f"{settings.backend_base_url.rstrip('/')}/health/live",
                headers={
                    "Authorization": f"Bearer {settings.backend_service_token.get_secret_value()}"
                },
                timeout=5,
                follow_redirects=False,
            )
            facts["backend"] = {
                "status": "http_reachable",
                "http_status": response.status_code,
                "authenticated_health": "passed" if response.status_code == 200 else "failed",
            }
        except httpx.HTTPError:
            facts["backend"] = {"status": "unreachable", "authenticated_health": "failed"}
    if settings.telegram_bot_token is None:
        facts["telegram"] = {"status": "not_configured", "identity_check": "pending"}
    else:
        try:
            response = client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/getMe",
                timeout=5,
                follow_redirects=False,
            )
            valid = response.status_code == 200 and response.json().get("ok") is True
            facts["telegram"] = {
                "status": "identity_verified" if valid else "identity_failed",
                "http_status": response.status_code,
                "staff_delivery": "not_attempted",
            }
        except (httpx.HTTPError, ValueError):
            facts["telegram"] = {"status": "unreachable_or_invalid_response"}
    facts["m6"] = {
        "enabled": settings.m6_enabled,
        "context_configured": settings.m6_contexts_file is not None,
        "calibration_configured": settings.m6_calibration_file is not None,
        "deployment": "research_only_clinical_gate_pending",
    }
    return facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        facts = audit(Settings(), client)
    save_new(args.output, facts)
    for name in ("postgres", "mqtt", "backend", "telegram"):
        print(f"CONNECTION | {name.upper()} | {facts[name]['status'].upper()}")
    print("CONNECTION | LIVE INTEGRATION | PENDING | no clinical messages sent")


if __name__ == "__main__":
    main()
