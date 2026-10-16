"""Fail-closed verification tooling, not a substitute for remote acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.phase6_acceptance import (
    CONNECTED_GATES,
    assess,
    check_snapshot,
    create_profile,
    digest,
    evidence_template,
    fresh_output,
    junit_summary,
    preflight,
    snapshot,
    verify_environment,
    write_json,
)
from tools.phase6_observe import observation, validate_config


def test_frozen_source_and_causal_configuration_are_verified() -> None:
    result = preflight()
    assert result["status"] == "PASS"
    assert result["python_supported"]
    assert result["m6_configuration"]["baseline_seconds"] == 900
    assert result["c1_status"] == "NOT RUN"


def test_missing_or_different_c1_is_not_a_pass(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.py"
    assert preflight(candidate)["status"] == "FAIL"
    candidate.write_text("# different candidate\n")
    assert preflight(candidate)["status"] == "FAIL"


def test_junit_errors_and_skips_cannot_be_hidden(tmp_path: Path) -> None:
    path = tmp_path / "results.xml"
    path.write_text("""<testsuites><testsuite errors="0">
      <testcase classname="test_demo" name="pass"/>
      <testcase classname="test_postgres" name="missing"><skipped/></testcase>
      <testcase classname="tests.test_phase5_granite" name="disabled"><skipped/></testcase>
      </testsuite></testsuites>""")
    result = junit_summary(path, granite_required=False)
    assert (result["passed"], result["failed"], result["skipped"]) == (1, 0, 2)
    assert result["status"] == "BLOCKED"
    assert len(result["required_skips"]) == len(result["optional_disabled_granite_skips"]) == 1
    assert len(junit_summary(path, granite_required=True)["required_skips"]) == 2
    path.write_text('<testsuite errors="1"><testcase name="broken"><error/></testcase></testsuite>')
    assert junit_summary(path, granite_required=False)["status"] == "FAIL"
    path.write_text('<testsuites><testsuite errors="0"/></testsuites>')
    assert junit_summary(path, granite_required=False)["status"] == "FAIL"


def test_evidence_directory_never_overwrites_or_enters_checkout(tmp_path: Path) -> None:
    from tools.phase6_acceptance import ROOT

    with pytest.raises(ValueError, match="outside"):
        fresh_output(ROOT / "artifacts/phase6")
    with pytest.raises(FileExistsError):
        fresh_output(tmp_path)


def test_verification_refuses_shared_or_remote_database(tmp_path: Path) -> None:
    profile = tmp_path / "runtime.json"
    write_json(profile, {"isolated_lab": True, "broker": {"host": "127.0.0.1"}})
    (tmp_path / "credentials.json").write_text("{}")
    base = {"SENTINEL_TEST_PHASE4_CONFIG": str(profile)}
    for database in ("postgresql://localhost/team", "postgresql://remote/sentinel_phase6_test"):
        with pytest.raises(ValueError, match="dedicated"):
            verify_environment(base | {"SENTINEL_TEST_DATABASE_URL": database})
    verify_environment(
        base | {"SENTINEL_TEST_DATABASE_URL": "postgresql://localhost/sentinel_phase6_test"}
    )
    write_json(profile, {"isolated_lab": False, "broker": {"host": "127.0.0.1"}})
    with pytest.raises(ValueError, match="isolated"):
        verify_environment(
            base | {"SENTINEL_TEST_DATABASE_URL": "postgresql://localhost/sentinel_phase6_test"}
        )


def test_connected_pass_needs_all_gates_and_retained_evidence(tmp_path: Path) -> None:
    path = tmp_path / "connected.json"
    data = evidence_template()
    data["run_id"] = "demo_B"
    write_json(path, data)
    assert assess(path)["status"] == "BLOCKED"
    data["gates"]["offline"]["status"] = "PASS"
    write_json(path, data)
    with pytest.raises(ValueError, match="retained evidence"):
        assess(path)
    receipt = tmp_path / "operator-results.txt"
    receipt.write_text("Fictional test of evidence integrity only; not actual backend proof.\n")
    for key in CONNECTED_GATES:
        data["gates"][key] = {
            "status": "PASS",
            "reason": "Operator assertion for fixture",
            "evidence": [{"path": receipt.name, "sha256": digest(receipt)}],
        }
    write_json(path, data)
    result = assess(path)
    assert result["status"] == "PASS"
    assert result["verification_basis"].startswith("Operator-reported")
    data["granite_enabled"] = True
    write_json(path, data)
    assert assess(path)["status"] == "BLOCKED"
    data["gates"]["offline"]["status"] = "FAIL"
    write_json(path, data)
    assert assess(path)["status"] == "FAIL"
    receipt.write_text("changed")
    with pytest.raises(ValueError, match="changed evidence"):
        assess(path)


def test_connected_gate_cannot_lose_owner_or_escape_evidence_root(tmp_path: Path) -> None:
    path = tmp_path / "connected.json"
    data = evidence_template()
    del data["gates"]["stale_rejection"]
    write_json(path, data)
    with pytest.raises(ValueError, match="all declared gates"):
        assess(path)
    data = evidence_template()
    data["gates"]["offline"]["evidence"] = [{"path": "../external.txt", "sha256": "bad"}]
    write_json(path, data)
    with pytest.raises(ValueError, match="stay inside"):
        assess(path)


def test_snapshot_contains_uncommitted_source_not_credentials_or_data(tmp_path: Path) -> None:
    import tarfile

    result = snapshot(tmp_path)
    assert result["archive_sha256"] == digest(tmp_path / result["archive"])
    with tarfile.open(tmp_path / result["archive"]) as archive:
        names = archive.getnames()
        assert "tools/phase6_acceptance.py" in names
        assert "src/sentinelward/phase5.py" in names  # currently uncommitted, must not be lost
        assert "src/sentinelward/m6.py" in names
        assert ".env" not in names
        assert not any(n.startswith((".git/", ".venv/", "data/", "models/")) for n in names)
    assert check_snapshot(tmp_path / "source-manifest.json")["status"] == "PASS"
    manifest = json.loads((tmp_path / "source-manifest.json").read_text("utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    write_json(tmp_path / "source-manifest.json", manifest)
    with pytest.raises(ValueError, match="differs"):
        check_snapshot(tmp_path / "source-manifest.json")


def test_private_profile_is_template_only_and_validates_real_contracts(tmp_path: Path) -> None:
    from sentinelward.phase5_factory import Phase5Configuration
    from tools.phase4_lab import configure

    broker = tmp_path / "broker"
    configure(broker, tmp_path, 18883)
    output = tmp_path / "private"
    output.mkdir()
    result = create_profile(
        output, broker / "runtime.json", "postgresql://localhost/sentinel_phase6_fixture"
    )
    assert result["status"] == "PASS"
    assert not result["writer_enabled"] and not result["actual_telegram"]
    profile = Phase5Configuration.model_validate_json((output / "phase5.json").read_bytes())
    assert profile.writer is None
    assert {c.principal.role for c in profile.staff_credentials} == {"it", "nurse", "doctor"}
    environment = (output / "environment.sh").read_text("utf-8")
    assert "SENTINEL_EXTERNAL_EFFECT_MODE=simulate" in environment
    assert "TELEGRAM_BOT_TOKEN" not in environment
    assert "SENTINEL_BACKEND_SERVICE_TOKEN" in environment
    assert "token" not in json.dumps(result)


def test_observer_records_identity_without_raw_payload_or_secrets() -> None:
    from sentinelward.m6_demo import synthetic_frame

    frame = synthetic_frame(0)
    payload = frame.model_dump_json().encode()
    row = observation("ward/bed/B01/vitals", payload, 1000, "run_B")
    assert row["validation"] == "VALID"
    assert row["identity_matches_observed_run"] is None
    assert not {"ecg", "ppg", "abp", "nibp", "reason", "payload"}.intersection(row)
    invalid = observation("ward/request", b'{"secret":"do not retain"}', 1000, "run_B")
    assert invalid["validation"] == "INVALID"
    assert "do not retain" not in json.dumps(invalid)
    score = {
        "v": 1,
        "type": "score",
        "bed_id": "B01",
        "model": "M6",
        "model_version": "m6-research-0.3.4",
        "window_start": 0,
        "window_s": 10,
        "score": 0.0,
        "label": "warming_up",
        "reason": "Research",
        "extra": {"demo_run_id": "run_A", "episode_id": "episode_A"},
    }
    stale = observation("ward/bed/B01/score/M6", json.dumps(score).encode(), 10000, "run_B")
    assert stale["identity_matches_observed_run"] is False
    assert stale["episode_id"] == "episode_A"


def test_observer_refuses_unprotected_remote_access_and_missing_credentials(monkeypatch) -> None:
    from tools.phase6_acceptance import ROOT

    config = json.loads((ROOT / "fixtures/phase6-observer.example.json").read_text())
    monkeypatch.delenv("PHASE6_OBSERVER_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="password"):
        validate_config(config)
    monkeypatch.setenv("PHASE6_OBSERVER_PASSWORD", "fictional-test-only")
    monkeypatch.setenv("SENTINEL_BACKEND_SERVICE_TOKEN", "fictional-service-only")
    validate_config(config)
    config["broker"]["host"] = "external.test"
    with pytest.raises(ValueError, match="non-TLS"):
        validate_config(config)
    config["broker"]["host"] = "127.0.0.1"
    config["probes"][0]["url"] = "http://127.0.0.1/health?token=secret"
    with pytest.raises(ValueError, match="credentials"):
        validate_config(config)
