from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import psycopg
from pydantic import SecretStr

from sentinelward.config import Settings
from sentinelward.connectivity import audit


def test_missing_services_report_pending_and_do_not_call_remote_endpoints() -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        patch("sentinelward.connectivity.psycopg.connect", side_effect=psycopg.OperationalError),
        patch("sentinelward.connectivity.socket.create_connection", side_effect=OSError),
    ):
        report = audit(Settings(), client)
    assert report["backend"]["status"] == "not_configured"
    assert report["telegram"]["status"] == "not_configured"
    assert report["mqtt"]["authenticated_publish_subscribe"] == "pending"
    assert report["postgres"]["status"] == "unreachable_or_auth_failed"
    assert not calls and report["clinical_messages_sent"] == 0


def test_read_only_health_checks_never_expose_secrets_or_follow_redirects() -> None:
    secret = "never-emit-this-token"
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "api.telegram.org":
            return httpx.Response(200, json={"ok": True, "result": {"id": 123}})
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(302, headers={"Location": "https://untrusted.invalid"})

    settings = Settings(
        backend_base_url="https://backend.invalid",
        backend_service_token=SecretStr(secret),
        telegram_bot_token=SecretStr(secret),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        patch("sentinelward.connectivity.psycopg.connect", side_effect=psycopg.OperationalError),
        patch("sentinelward.connectivity.socket.create_connection", side_effect=OSError),
    ):
        report = audit(settings, client)
    assert report["backend"]["authenticated_health"] == "failed"
    assert report["telegram"]["status"] == "identity_verified"
    assert all(request.method == "GET" for request in calls)
    assert len(calls) == 2 and secret not in json.dumps(report)
