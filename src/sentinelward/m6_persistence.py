from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from sentinelward.contracts import BedId, ScoreMessage, VitalsMessage
from sentinelward.m6 import MODEL_VERSION, EpisodeContext, M6Config, M6State, step


def load_contexts(path: Path) -> dict[str, EpisodeContext]:
    return TypeAdapter(dict[BedId, EpisodeContext]).validate_json(path.read_bytes())


def restored_state(raw: object, context: EpisodeContext, config: M6Config) -> M6State:
    if raw is None:
        return M6State(context=context, config=config)
    state = M6State.model_validate(raw)
    if state.context != context:
        if (
            context.start_ts <= state.context.start_ts
            or context.start_ts <= state.last_ts
            or context.episode_id == state.context.episode_id
        ):
            raise ValueError("episode change requires a new ID and later start time")
        return M6State(context=context, config=config)
    if state.config != config:
        raise ValueError(
            "M6 configuration changed within an episode; restart with reviewed context"
        )
    if state.model_version != MODEL_VERSION or (
        isinstance(raw, dict) and raw.get("model_version") != MODEL_VERSION
    ):
        raise ValueError("M6 algorithm version changed; a new reviewed episode context is required")
    return state


def delivery_key(context: EpisodeContext, score: ScoreMessage) -> str:
    identity = f"{context.episode_id}:{score.bed_id}:{score.window_start}:{score.model_version}"
    return "m6:" + hashlib.sha256(identity.encode()).hexdigest()


@dataclass(slots=True)
class InMemoryM6Handler:
    contexts: dict[str, EpisodeContext]
    config: M6Config = field(default_factory=M6Config)
    states: dict[str, object] = field(default_factory=dict)
    outbox: dict[str, ScoreMessage] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def handle_m6(self, message: VitalsMessage | ScoreMessage) -> ScoreMessage | None:
        async with self._lock:
            context = self.contexts.get(message.bed_id)
            if context is None:
                raise ValueError("M6 episode context is not configured for this bed")
            state = restored_state(self.states.get(message.bed_id), context, self.config)
            score = step(state, message)
            self.states[message.bed_id] = state.model_dump(mode="json")
            if score is not None:
                self.outbox.setdefault(delivery_key(context, score), score)
            return score


@dataclass(frozen=True, slots=True)
class PostgresM6Handler:
    database_url: str
    contexts: dict[str, EpisodeContext]
    config: M6Config = field(default_factory=M6Config)

    async def handle_m6(self, message: VitalsMessage | ScoreMessage) -> ScoreMessage | None:
        context = self.contexts.get(message.bed_id)
        if context is None:
            raise ValueError("M6 episode context is not configured for this bed")
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            # Transaction-scoped per-bed lock also covers concurrent first inserts.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(6006, %s)", (int(message.bed_id[1:]),)
            )
            cursor = await connection.execute(
                "SELECT state FROM automation.m6_states WHERE bed_id = %s", (message.bed_id,)
            )
            row = await cursor.fetchone()
            state = restored_state(row[0] if row else None, context, self.config)
            score = step(state, message)
            await connection.execute(
                "INSERT INTO automation.m6_states (bed_id, state) VALUES (%s, %s) "
                "ON CONFLICT (bed_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
                (message.bed_id, Jsonb(state.model_dump(mode="json"))),
            )
            if score is not None:
                topic = f"ward/bed/{score.bed_id}/score/M6"
                payload = {"topic": topic, "body": score.model_dump(mode="json"), "qos": 1}
                await connection.execute(
                    """INSERT INTO automation.outbox_events (
                    outbox_id, delivery_key, destination, payload, correlation_id,
                    status, attempt_count, next_attempt_at, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, 'pending', 0, now(), now(), now())
                    ON CONFLICT (delivery_key) DO NOTHING""",
                    (
                        uuid4(),
                        delivery_key(context, score),
                        f"mqtt:{topic}",
                        Jsonb(payload),
                        f"{score.bed_id}:{score.window_start}:M6",
                    ),
                )
        return score


def config_from_artifact(path: Path | None) -> M6Config:
    if path is None:
        return M6Config()
    from sentinelward.m6_evaluation import CalibrationArtifact

    artifact = CalibrationArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return artifact.config.model_copy(update={"calibration_id": artifact.artifact_id})
