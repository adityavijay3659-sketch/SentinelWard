"""Bounded local writer. It has no tool or operational-action interface."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr, ValidationError

from sentinelward.phase5_contracts import CompactComposition, Composition, FactSnapshot
from sentinelward.phase5_diagnostics import GenerationFailure
from sentinelward.phase5_facts import render_composition


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise GenerationFailure("duplicate_json_key", "response_json")
        output[key] = value
    return output


def _decode_completion(body: bytes, content_type: str) -> Any:
    """Consume bounded SSE without allowing a truncated stream to become a result."""
    if not content_type.startswith("text/event-stream"):
        return json.loads(body, object_pairs_hook=_unique_object)
    content: list[str] = []
    finish: str | None = None
    usage: dict[str, Any] = {}
    done = False
    try:
        events = body.decode("utf-8").replace("\r\n", "\n").split("\n\n")
        for event in events:
            lines = event.splitlines()
            if any(line and not line.startswith(("data:", ":")) for line in lines):
                raise GenerationFailure("response_schema_invalid", "stream")
            data = "\n".join(line[5:].lstrip(" ") for line in lines if line.startswith("data:"))
            if not data:
                continue
            if done:
                raise GenerationFailure("response_schema_invalid", "stream")
            if data == "[DONE]":
                done = True
                continue
            value = json.loads(data, object_pairs_hook=_unique_object)
            if not isinstance(value, dict) or not isinstance(value.get("choices"), list):
                raise GenerationFailure("response_schema_invalid", "stream")
            if isinstance(value.get("usage"), dict):
                usage = value["usage"]
            choices = value["choices"]
            if not choices:
                continue
            if len(choices) != 1 or not isinstance(choices[0], dict):
                raise GenerationFailure("response_schema_invalid", "stream")
            choice = choices[0]
            delta = choice.get("delta")
            if not isinstance(delta, dict) or finish is not None:
                raise GenerationFailure("response_schema_invalid", "stream")
            if delta.get("tool_calls") or delta.get("reasoning_content"):
                raise GenerationFailure("unexpected_tools_or_reasoning", "completion")
            fragment = delta.get("content")
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise GenerationFailure("response_schema_invalid", "stream")
                content.append(fragment)
            ending = choice.get("finish_reason")
            if ending is not None:
                if ending != "stop":
                    raise GenerationFailure("response_truncated", "completion")
                finish = ending
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationFailure("invalid_json", "stream") from exc
    if not done or finish != "stop":
        raise GenerationFailure("response_truncated", "completion")
    return {
        "choices": [{"finish_reason": finish, "message": {"content": "".join(content)}}],
        "usage": usage,
    }


class Writer(Protocol):
    @property
    def identity(self) -> str: ...

    async def compose(self, snapshot: FactSnapshot) -> Composition: ...


@dataclass(frozen=True)
class UnavailableWriter:
    identity: str = "unavailable"

    async def compose(self, snapshot: FactSnapshot) -> Composition:
        raise ConnectionError("local Granite is not configured")


@dataclass
class GraniteWriter:
    base_url: str
    model: str
    model_sha256: str
    build: str
    api_key: SecretStr
    client: httpx.AsyncClient | None = None
    last_metrics: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Granite must use an explicit loopback server URL")
        if len(self.model_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.model_sha256
        ):
            raise ValueError("model SHA-256 is required")

    @property
    def identity(self) -> str:
        return f"{self.model}:{self.model_sha256}:{self.build}:phase5-3"

    def request_payload(self, snapshot: FactSnapshot) -> dict[str, Any]:
        # No patient text, incident notes, addresses or device labels enter the prompt.
        codes = {
            "count": "c",
            "duration": "d",
            "state": "s",
            "scope": "q",
            "missing": "m",
            "action": "a",
        }
        kinds = "".join(
            codes["missing" if fact.status == "unavailable" else fact.predicate]
            for fact in snapshot.facts
        )
        fact_count = len(snapshot.facts)
        schema = CompactComposition.model_json_schema()
        schema["properties"]["wording"] = {
            "type": "string",
            "pattern": f"^[01]{{{fact_count}}}$",
            "minLength": fact_count,
            "maxLength": fact_count,
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Compose a concise report using the supplied facts. "
                        "Output JSON with v=2, order and wording. "
                        "Choose order source or reverse. wording has exactly fact_count binary "
                        "digits, one for each input kind in source order. "
                        "0 means plain wording, 1 means concise wording. "
                        "Kinds: c=count,d=duration,s=state,q=scope,m=missing,a=action. "
                        "All facts are mandatory; code supplies every fact and value. "
                        "Do not output text, IDs, additional fields or tools."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"fact_count": fact_count, "kinds": kinds}, separators=(",", ":")
                    ),
                },
            ],
            "response_format": {"type": "json_object", "schema": schema},
            "temperature": 0,
            "seed": 42,
            "max_tokens": 512,
            "chat_template_kwargs": {"thinking": False, "enable_thinking": False},
            "reasoning_effort": "none",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if len(json.dumps(payload).encode()) > 24_000:
            raise GenerationFailure("request_too_large", "request")
        return payload

    async def compose(self, snapshot: FactSnapshot) -> Composition:
        started = time.monotonic()
        payload = self.request_payload(snapshot)
        self.last_metrics = {
            "protocol": "phase5-3",
            "transport": "sse",
            "fact_count": len(snapshot.facts),
            "request_bytes": len(json.dumps(payload).encode()),
            "max_tokens": 512,
        }
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=120, follow_redirects=False, trust_env=False
        )
        try:
            async with client.stream(
                "POST",
                self.base_url.rstrip("/") + "/v1/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.api_key.get_secret_value()},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65_536:
                        raise GenerationFailure("response_too_large", "transport")
            self.last_metrics.update(
                inference_ms=int((time.monotonic() - started) * 1000),
                response_sha256=hashlib.sha256(body).hexdigest(),
                response_bytes=len(body),
            )
            validation_started = time.monotonic()
            try:
                value = _decode_completion(bytes(body), response.headers.get("content-type", ""))
            except json.JSONDecodeError as exc:
                raise GenerationFailure("invalid_json", "response_json") from exc
            if not isinstance(value, dict):
                raise GenerationFailure("response_schema_invalid", "response_schema")
            try:
                choice = value["choices"][0]
                message = choice["message"]
            except (KeyError, TypeError, IndexError) as exc:
                raise GenerationFailure("response_schema_invalid", "response_schema") from exc
            if not isinstance(choice, dict) or not isinstance(message, dict):
                raise GenerationFailure("response_schema_invalid", "response_schema")
            finish = choice.get("finish_reason")
            self.last_metrics["finish_reason"] = finish if finish in {"stop", "length"} else "other"
            usage = value.get("usage")
            for key in ("completion_tokens", "prompt_tokens", "total_tokens"):
                quantity = usage.get(key) if isinstance(usage, dict) else None
                if type(quantity) is int and quantity >= 0:
                    self.last_metrics[key] = quantity
            if choice.get("finish_reason") != "stop":
                raise GenerationFailure("response_truncated", "completion")
            if message.get("tool_calls") or message.get("reasoning_content"):
                raise GenerationFailure("unexpected_tools_or_reasoning", "completion")
            try:
                content = json.loads(message["content"], object_pairs_hook=_unique_object)
                compact = CompactComposition.model_validate(content)
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                raise GenerationFailure("invalid_json", "composition_json") from exc
            except ValidationError as exc:
                raise GenerationFailure("schema_invalid", "composition_schema") from exc
            composition = compact.expand(snapshot)
            render_composition(snapshot, composition)
            self.last_metrics["validation_ms"] = int((time.monotonic() - validation_started) * 1000)
            return composition
        except GenerationFailure as exc:
            self.last_metrics.update(error_code=exc.code, error_stage=exc.stage)
            raise
        except httpx.HTTPError:
            self.last_metrics.update(error_code="transport_error", error_stage="transport")
            raise
        finally:
            self.last_metrics["total_ms"] = int((time.monotonic() - started) * 1000)
            if own_client:
                await client.aclose()
