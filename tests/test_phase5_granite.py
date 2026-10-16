"""Actual local Granite workflow test; opt in with an isolated private profile."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from sentinelward.adapters.granite import GraniteWriter
from sentinelward.phase5_contracts import GenerateBriefing
from sentinelward.phase5_factory import Phase5Configuration
from tests.test_phase5 import authorize, incident_report, lab

CONFIG = os.getenv("SENTINEL_TEST_PHASE5_CONFIG")


@pytest.mark.integration
@pytest.mark.skipif(CONFIG is None, reason="isolated real Granite profile required")
@pytest.mark.asyncio
async def test_actual_granite_report_and_briefing_workflows(tmp_path):
    assert CONFIG is not None
    config = Phase5Configuration.model_validate_json(Path(CONFIG).read_bytes())
    assert config.writer is not None
    with config.writer.model_file.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == config.writer.model_sha256
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    agent.writer = GraniteWriter(
        config.writer.base_url,
        config.writer.model,
        config.writer.model_sha256,
        config.writer.build,
        config.writer.api_key,
    )
    report = await incident_report(agent, phase4, now)
    await agent.process_one_job()
    args = await authorize(agent, now, "real_briefing", "briefing", "WARD", role="nurse")
    briefing = await agent.generate_briefing(GenerateBriefing(**args))
    await agent.process_one_job()
    status = await agent.status()
    evidence = {
        "model_identity": agent.writer.identity,
        "jobs": status["jobs"],
        "report": status["records"]["report"][0],
        "briefing": status["records"]["briefing"][0],
        "scope": "Fictional software workflow; actual Granite, no clinical validation",
        "all_actual_workflows_generated": all(j["state"] == "accepted" for j in status["jobs"]),
    }
    evidence_path = os.getenv("SENTINEL_TEST_PHASE5_WORKFLOW_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(json.dumps(evidence, indent=2))
    assert report["narrative"]["generator"] == briefing["narrative"]["generator"] == "template"
    # This is the software fail-closed gate, not a model-acceptance assertion.
    # Acceptance remains a separately reported measured result, including failures.
    for kind in ("report", "briefing"):
        narrative = evidence[kind]["narrative"]
        assert narrative["verified"]
        assert narrative["generator"] in {"granite", "template"}
        assert narrative["generator"] == "granite" or narrative["fallback_reason"]
