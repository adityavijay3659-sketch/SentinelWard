"""Opt-in isolated Phase 5 construction; secrets and model assets stay outside Git."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field, SecretStr, model_validator

from sentinelward.adapters.granite import GraniteWriter, UnavailableWriter, Writer
from sentinelward.alerts import AlertStore
from sentinelward.contracts import StrictMessage
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase5 import Phase5Coordinator
from sentinelward.phase5_contracts import Principal, StaffProfile
from sentinelward.phase5_state import PostgresRepository


class WriterConfiguration(StrictMessage):
    base_url: str
    model: str
    model_file: Path
    model_sha256: str = Field(min_length=64, max_length=64)
    build: str = Field(min_length=1, max_length=96)
    api_key: SecretStr


class StaffCredential(StrictMessage):
    token: SecretStr
    principal: Principal


class Phase5Configuration(StrictMessage):
    v: int = 1
    isolated_lab: bool
    staff: StaffProfile
    report_profile: dict[str, str | bool] = Field(default_factory=dict)
    writer: WriterConfiguration | None = None
    staff_credentials: list[StaffCredential] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def isolated(self) -> Phase5Configuration:
        if type(self.v) is not int or self.v != 1 or not self.isolated_lab:
            raise ValueError("Phase 5 factory is isolated v1 only")
        return self


def build_phase5(
    path: Path, database_url: str, phase4: Phase4Coordinator, alerts: AlertStore
) -> Phase5Coordinator:
    config = Phase5Configuration.model_validate_json(path.read_bytes())
    writer: Writer = UnavailableWriter()
    if config.writer is not None:
        with config.writer.model_file.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != config.writer.model_sha256:
            raise ValueError("Granite artifact hash mismatch")
        writer = GraniteWriter(
            config.writer.base_url,
            config.writer.model,
            actual,
            config.writer.build,
            config.writer.api_key,
        )
    coordinator = Phase5Coordinator(
        PostgresRepository(database_url),
        phase4,
        alerts,
        config.staff,
        config.report_profile,
        writer,
    )
    phase4.after_control = coordinator.handle_control
    return coordinator
