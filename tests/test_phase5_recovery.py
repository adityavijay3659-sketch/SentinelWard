"""Regression evidence for the actual report failure and bounded generation repair."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from sentinelward.adapters.granite import GraniteWriter, UnavailableWriter
from sentinelward.contracts import Verdict
from sentinelward.phase4_reference import create_reference_backend
from sentinelward.phase5_contracts import (
    CompactComposition,
    Composition,
    EditReport,
    Fact,
    FactSnapshot,
    GenerateBriefing,
    HumanCommand,
    Sentence,
)
from sentinelward.phase5_diagnostics import GenerationFailure
from sentinelward.phase5_facts import render_composition, union_ms
from tests.test_demo_lifecycle import _frame
from tests.test_phase4 import control, verdict
from tests.test_phase5 import FixtureWriter, authorize, incident_report, lab


def snapshot(count=5):
    return FactSnapshot(
        snapshot_id="facts_test",
        run_id="runA",
        kind="report",
        since=0,
        as_of=1,
        facts=[
            Fact(
                fact_id=f"f{i}",
                predicate="count",
                subject=f"source_{i}",
                value=i,
                unit="events",
                status="observed",
                source="fixture",
                revision=1,
                start_ts=0,
                end_ts=1,
            )
            for i in range(count)
        ],
    )


def test_original_duplicate_and_missing_fact_is_rejected_and_classified():
    source = snapshot()
    composition = Composition(
        sentences=[Sentence(phrase_id="count", fact_id=f"f{i}") for i in [4, 0, 1, 2, 4]]
    )
    with pytest.raises(GenerationFailure) as error:
        render_composition(source, composition)
    assert error.value.code == "duplicate_fact_id"
    for count in (5, 15, 30, 42, 64):
        source = snapshot(count)
        for order in ("source", "reverse"):
            compact = CompactComposition(v=2, order=order, wording="1" * count)
            expanded = compact.expand(source)
            assert len({s.fact_id for s in expanded.sentences}) == count
            assert all(str(f.value) in render_composition(source, expanded) for f in source.facts)
    with pytest.raises(GenerationFailure, match="wording_count_mismatch"):
        CompactComposition(v=2, order="source", wording="1").expand(snapshot())


@pytest.mark.parametrize(
    "content,finish,code",
    [
        ('{"v":2,"order":"source","wording":"11111"}', "length", "response_truncated"),
        ('{"v":2,"order":"source","wording":"11111","text":"safe"}', "stop", "schema_invalid"),
        ('{"v":2,"order":"source","wording":"1"}', "stop", "wording_count_mismatch"),
        (
            '{"v":2,"order":"source","wording":"11111","wording":"00000"}',
            "stop",
            "duplicate_json_key",
        ),
        ("not json", "stop", "invalid_json"),
    ],
)
@pytest.mark.asyncio
async def test_provider_failures_have_safe_diagnostics(content, finish, code):
    def response(request):
        return httpx.Response(
            200, json={"choices": [{"finish_reason": finish, "message": {"content": content}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        writer = GraniteWriter(
            "http://127.0.0.1:1", "granite", "a" * 64, "11433", SecretStr("not-logged"), client
        )
        with pytest.raises(GenerationFailure) as error:
            await writer.compose(snapshot())
        assert error.value.code == code
        assert writer.last_metrics["error_code"] == code
        assert "not-logged" not in json.dumps(writer.last_metrics)
        assert content not in json.dumps(writer.last_metrics)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant", ["valid", "missing_done", "length", "reasoning", "duplicate", "after_done"]
)
async def test_streamed_composition_is_complete_or_rejected(variant):
    content = '{"v":2,"order":"source","wording":"11111"}'
    first = {"choices": [{"delta": {"content": content[:20]}, "finish_reason": None}]}
    last = {"choices": [{"delta": {"content": content[20:]}, "finish_reason": "stop"}]}
    expected = None
    if variant == "length":
        last["choices"][0]["finish_reason"] = "length"
        expected = "response_truncated"
    if variant == "reasoning":
        first["choices"][0]["delta"]["reasoning_content"] = "Forbidden"
        expected = "unexpected_tools_or_reasoning"
    events = ["data: " + json.dumps(first), "data: " + json.dumps(last)]
    if variant == "duplicate":
        events[0] = 'data: {"choices":[],"choices":[]}'
        expected = "duplicate_json_key"
    if variant == "missing_done":
        expected = "response_truncated"
    else:
        events.append("data: " + json.dumps({"choices": [], "usage": {"completion_tokens": 20}}))
        events.append("data: [DONE]")
    if variant == "after_done":
        events.append("data: " + json.dumps(first))
        expected = "response_schema_invalid"
    body = ("\n\n".join(events) + "\n\n").encode()

    def response(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        writer = GraniteWriter(
            "http://127.0.0.1:1", "granite", "a" * 64, "11433", SecretStr("private"), client
        )
        if expected is not None:
            with pytest.raises(GenerationFailure) as error:
                await writer.compose(snapshot())
            assert error.value.code == expected
        else:
            assert len((await writer.compose(snapshot())).sentences) == 5
            assert writer.last_metrics["completion_tokens"] == 20


@pytest.mark.asyncio
async def test_failed_generation_preserves_exact_pdf_and_exposes_job_outcome(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path, FixtureWriter(invalid=True))
    report = await incident_report(agent, phase4, now)
    body, metadata = await agent.pdf(report["record_id"])
    await agent.process_one_job()
    state = await agent.status()
    after = state["records"]["report"][0]
    assert after["revision"] == report["revision"]
    again, identity = await agent.pdf(report["record_id"])
    assert (again, identity) == (body, metadata)
    app = create_reference_backend(
        phase4, service_token="service", phase5=agent, staff_tokens={"it-token": ("staff:it", "it")}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        result = await client.get(
            "/api/reports/" + report["record_id"], headers={"Authorization": "Bearer it-token"}
        )
        assert result.json()["generation"]["reason"] == "unknown_fact_id"


@pytest.mark.asyncio
async def test_disabled_writer_never_queues_inference(tmp_path):
    agent, phase4, _alerts, now, store = await lab(tmp_path)
    agent.writer = UnavailableWriter()
    report = await incident_report(agent, phase4, now)
    assert report["narrative"]["fallback_reason"] == "model_disabled"
    assert report["revision"] == 1 and not (await agent.status())["jobs"]
    wires = [
        e["payload"]["body"]
        for e in store.outbox.values()
        if e["payload"]["topic"] == "ward/record" and e["payload"]["body"]["kind"] == "report"
    ]
    assert len(wires) == 1 and wires[0]["data"]["narrative"]["fallback_reason"] == "model_disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["reset", "human_edit", "undo"])
async def test_obsolete_inference_cancelled_without_waiting_for_model(tmp_path, cause):
    writer = FixtureWriter(wait=asyncio.Event())
    agent, phase4, _alerts, now, _store = await lab(tmp_path, writer)
    report = await incident_report(agent, phase4, now)
    running = asyncio.create_task(agent.process_one_job())
    await writer.started.wait()
    if cause == "reset":
        now[0] += 1000
        await phase4.handle_control(control("reset", "runA", now[0]))
    elif cause == "human_edit":
        args = await authorize(agent, now, "edit", "edit_report", report["record_id"], revision=1)
        await agent.edit_report(
            report["record_id"], EditReport(**args, description="Human reviewed")
        )
    else:
        async with agent.repository.transaction() as unit:
            action_id = next(
                key for key, action in unit.list("action") if action["action"] == "draft_report"
            )
        args = await authorize(agent, now, "undo", "undo", action_id, revision=1)
        await agent.undo(action_id, HumanCommand(**args))
    assert await asyncio.wait_for(running, 1)
    assert all(j["state"] == "retired" for j in (await agent.status())["jobs"])


@pytest.mark.asyncio
async def test_eight_queued_jobs_overflow_and_expiry_never_calls_model(tmp_path):
    writer = FixtureWriter()
    agent, _phase4, _alerts, now, _store = await lab(tmp_path, writer)
    for i in range(9):
        args = await authorize(agent, now, f"b{i}", "briefing", "WARD", role="nurse")
        latest = await agent.generate_briefing(GenerateBriefing(**args))
    assert len((await agent.status())["jobs"]) == 8
    assert latest["narrative"]["fallback_reason"] == "queue_full"
    now[0] += 121_000
    for _ in range(8):
        assert await agent.process_one_job()
    assert writer.calls == 0
    assert all(
        j["state"] == "fallback" and j["reason"] == "TimeoutError"
        for j in (await agent.status())["jobs"]
    )


@pytest.mark.asyncio
async def test_native_coverage_coalesces_without_bridging_expired_trust(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    base = now[0]
    await phase4.observe(_frame(base, 0, bed_id="B01"))
    await agent.observe_verdict(
        verdict(now, Verdict.NORMAL).model_copy(update={"last_trusted_ts": None})
    )
    await agent.observe_lifecycle()
    now[0] += 1000
    await agent.observe_lifecycle()
    now[0] += 10_000
    await agent.observe_lifecycle()
    await phase4.observe(_frame(now[0], 0, bed_id="B01"))
    await agent.observe_verdict(
        verdict(now, Verdict.NORMAL).model_copy(update={"last_trusted_ts": None})
    )
    await agent.observe_lifecycle()
    now[0] += 1000
    await agent.observe_lifecycle()
    async with agent.repository.transaction() as unit:
        intervals = [
            (r["start_ts"], r["end_ts"])
            for _, r in unit.list("coverage")
            if r["bed_id"] == "B01" and r["state"] == "trusted"
        ]
    assert union_ms(intervals, base, now[0]) == 4000
    assert len(intervals) == 2


@pytest.mark.asyncio
async def test_constant_native_coverage_has_bounded_rows_and_exact_duration(tmp_path):
    agent, _phase4, _alerts, now, _store = await lab(tmp_path)
    base = now[0]
    for second in range(120):
        now[0] = base + second * 1000
        await agent.observe_lifecycle()
    async with agent.repository.transaction() as unit:
        rows = unit.list("coverage")
    assert len(rows) == 3
    assert all(r["end_ts"] - r["start_ts"] == 119_000 for _, r in rows)
