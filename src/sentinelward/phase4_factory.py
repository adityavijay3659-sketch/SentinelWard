"""Explicit configuration for isolated handlers; live capabilities fail closed."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, model_validator

from sentinelward.contracts import StrictMessage
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase4_adapters import BrokerSettings, EvidenceFiles, MosquittoBrokerControl
from sentinelward.phase4_backend import LocalProjection
from sentinelward.phase4_state import ContainmentPolicy, Device, PostgresAgentRepository


class Phase4Configuration(StrictMessage):
    v: int = 1
    isolated_lab: bool = False
    inventory: list[Device] = Field(min_length=1, max_length=12)
    broker: BrokerSettings
    evidence_root: Path
    containment_policy: ContainmentPolicy | None = None

    @model_validator(mode="after")
    def isolated_only(self) -> Phase4Configuration:
        if self.v != 1:
            raise ValueError("unsupported Phase 4 configuration version")
        if not self.isolated_lab:
            raise ValueError(
                "local handlers require isolated_lab; inject deployed backend ports separately"
            )
        if any(not device.lab_owned for device in self.inventory):
            raise ValueError("isolated handler configuration may control only lab-owned devices")
        if self.broker.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("isolated broker must be loopback")
        if len({d.device_id for d in self.inventory}) != len(self.inventory) or len(
            {d.bed_id for d in self.inventory}
        ) != len(self.inventory):
            raise ValueError("duplicate bed/device inventory identity")
        if len({d.username for d in self.inventory}) != len(self.inventory) or len(
            {d.client_id for d in self.inventory}
        ) != len(self.inventory):
            raise ValueError("broker identities must be unique")
        return self


def build_phase4(path: Path, database_url: str) -> Phase4Coordinator:
    configuration = Phase4Configuration.model_validate(json.loads(path.read_text(encoding="utf-8")))
    repository = PostgresAgentRepository(database_url)
    local = LocalProjection(repository)
    return Phase4Coordinator(
        repository=repository,
        inventory={d.device_id: d for d in configuration.inventory},
        broker=MosquittoBrokerControl(configuration.broker),
        projection=local,
        watch=local,
        evidence=EvidenceFiles(configuration.evidence_root),
        policy=configuration.containment_policy,
        isolated_lab=configuration.isolated_lab,
    )
