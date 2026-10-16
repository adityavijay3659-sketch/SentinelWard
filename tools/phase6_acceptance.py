"""Source-checkout verification; never deploys or turns operator assertions into live proof.

Run with python -m tools.phase6_acceptance --help. Private outputs belong outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
M6_SHA256 = "4b1c9084935a8d253fd00d67f9011c464281d79928cbd9a2f4d7c90d2b66c4c7"
C1_SHA256 = "ede527738073fb8774406773da4970a8d9ee034caf78fe185f5d2351ecafad9f"
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT RUN"}
CONNECTED_GATES = {
    "target_identity": "Architecture, Python, source/config identity and clock sync",
    "transport_security": "Authenticated broker ACLs/TLS or documented isolated loopback tunnel",
    "all_verdicts": "Actual decision stack: all eight routes, roles and deterministic outputs",
    "run_identity": "Current run and episode propagate through scores, outbox, backend and UI",
    "stale_rejection": "Delayed old score/record rejected before projections and new actions",
    "offline": "B03/B04/B07 end: OFFLINE, last values, offline_since and no silence-created flag",
    "urgent_precedence": "BOTH and offline never cancel supported urgent outcomes",
    "alert_ladder": "Simulated Telegram, real screen ACK, escalation and durable restart",
    "containment": "Actual A2/A3/A4 effect, failure, evidence, scoped exactly-once undo",
    "narratives": "Actual backend/UI A5 review/PDF/attestation, A7 counts, A8 causal qualifiers",
    "fault_recovery": "Isolated DB/MQTT/backend/control outages: recovery without duplication",
    "golden_20_minutes": "Real-time twelve-bed scenario, producer event logs and actual UI",
    "reset_second_run": "New run/episodes, clean runtime and retained historical audit",
    "load_measurements": "Full-stack latency, message gaps, queues, CPU/memory, denominators",
}
OPTIONAL_GATES = {"granite_target": "Target model identity, deadlines and paired full-stack load"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def fresh_output(path: Path) -> Path:
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("evidence must be outside the source checkout")
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", "utf-8")


def preflight(c1: Path | None = None) -> dict[str, Any]:
    import sentinelward.m6 as m6

    source = ROOT / "src/sentinelward/m6.py"
    imported = Path(m6.__file__).resolve()
    config = m6.M6Config().model_dump(mode="json")
    expected = {"baseline_seconds": 900, "cuff_max_age_ms": 120000, "evidence_threshold": 0.6}
    intact = digest(source) == M6_SHA256 and imported == source.resolve()
    intact = intact and m6.MODEL_VERSION == "m6-research-0.3.4"
    intact = intact and all(config[key] == value for key, value in expected.items())
    c1_status = "NOT RUN"
    if c1 is not None:
        c1_status = "PASS" if c1.is_file() and digest(c1) == C1_SHA256 else "FAIL"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    versions = {}
    requirements = project["dependencies"] + project["optional-dependencies"]["dev"]
    for requirement in requirements:
        name = re.split(r"[\[<>=!~; ]", requirement)[0]
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "UNAVAILABLE"
    files = [
        p
        for folder in ("src", "tools", "tests", "migrations", "fixtures")
        for p in (ROOT / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    ]
    files += [ROOT / "pyproject.toml", ROOT / "uv.lock"]
    fingerprint = "\n".join(f"{p.relative_to(ROOT).as_posix()}:{digest(p)}" for p in sorted(files))
    return {
        "schema_version": 1,
        "scope": "local source identity; not connected acceptance",
        "status": "PASS" if intact and c1_status != "FAIL" else "FAIL",
        "python": platform.python_version(),
        "python_supported": sys.version_info[:2] == (3, 12),
        "architecture": platform.machine(),
        "platform": platform.system(),
        "project_version": project["version"],
        "dependency_versions": versions,
        "source_tree_sha256": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        "source_file_count": len(files),
        "installed_metadata_version": importlib.metadata.version("sentinelward"),
        "git_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "working_tree": git("status", "--short"),
        "source_path": str(imported),
        "m6_sha256": digest(source),
        "reference_version": m6.MODEL_VERSION,
        "m6_configuration": config,
        "c1_status": c1_status,
        "c1_sha256": digest(c1) if c1 is not None and c1.is_file() else None,
        "free_bytes": shutil.disk_usage(ROOT).free,
        "recorded_at_ms": time.time_ns() // 1_000_000,
    }


def junit_summary(path: Path, *, granite_required: bool) -> dict[str, Any]:
    """Count cases, not nested suite totals. Missing/empty JUnit is never success."""
    cases = list(ET.parse(path).getroot().iter("testcase"))
    passed = failed = skipped = 0
    required_skips: list[str] = []
    optional_skips: list[str] = []
    failures: list[str] = []
    for case in cases:
        identity = case.get("classname", "") + "::" + case.get("name", "")
        if case.find("failure") is not None or case.find("error") is not None:
            failed += 1
            failures.append(identity)
        elif case.find("skipped") is not None:
            skipped += 1
            if not granite_required and "test_phase5_granite" in identity:
                optional_skips.append(identity)
            else:
                required_skips.append(identity)
        else:
            passed += 1
    # Collection/setup errors can be suite-level on some pytest/plugin versions.
    suite_errors = sum(
        int(s.get("errors", "0")) for s in ET.parse(path).getroot().iter("testsuite")
    )
    status = "FAIL" if failed or suite_errors else "BLOCKED" if required_skips else "PASS"
    if not cases:
        status = "FAIL"
    return {
        "status": status,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "suite_errors": suite_errors,
        "required_skips": required_skips,
        "optional_disabled_granite_skips": optional_skips,
        "failures": failures,
    }


def verify_environment(environment: dict[str, str]) -> None:
    database = urlparse(environment.get("SENTINEL_TEST_DATABASE_URL", ""))
    if (
        database.scheme != "postgresql"
        or database.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not database.path.startswith("/sentinel_phase6_")
    ):
        raise ValueError("use a loopback dedicated database named sentinel_phase6_<identifier>")
    profile = Path(environment.get("SENTINEL_TEST_PHASE4_CONFIG", ""))
    config = json.loads(profile.read_text("utf-8"))
    if config.get("isolated_lab") is not True or config["broker"]["host"] != "127.0.0.1":
        raise ValueError("verification requires an isolated loopback Phase 4 lab")
    if not (profile.parent / "credentials.json").is_file():
        raise ValueError("dedicated broker credentials are unavailable")


def run_check(name: str, command: list[str], output: Path, env: dict[str, str]) -> dict[str, Any]:
    began = time.monotonic()
    # Logs are private and may include dependency exception details; do not publish verbatim.
    with (output / f"{name}.log").open("wb") as stream:
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
            status = "PASS" if completed.returncode == 0 else "FAIL"
            code: int | None = completed.returncode
        except subprocess.TimeoutExpired:
            status, code = "FAIL", None
    print(f"{name}: {status}", flush=True)
    return {
        "name": name,
        "status": status,
        "exit_code": code,
        "elapsed_s": round(time.monotonic() - began, 3),
    }


def verify(output: Path, *, c1: Path | None, granite: bool) -> dict[str, Any]:
    frozen = preflight(c1)
    if frozen["status"] != "PASS" or not frozen["python_supported"]:
        raise ValueError("frozen source or Python preflight failed; no tests started")
    verify_environment(dict(os.environ))
    if granite and not os.environ.get("SENTINEL_TEST_PHASE5_CONFIG"):
        raise ValueError("--granite requires an explicit private model profile")
    if shutil.disk_usage(output).free < 1_073_741_824:
        raise ValueError("at least 1 GiB free scratch space required")
    # Do not inherit a developer's live deployment or Telegram credentials.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("SENTINEL_")}
    allowed = (
        "SENTINEL_TEST_DATABASE_URL",
        "SENTINEL_TEST_PHASE4_CONFIG",
        "SENTINEL_TEST_VITALDB_ROOT",
    )
    for key in allowed:
        if key in os.environ:
            environment[key] = os.environ[key]
    if granite:
        environment["SENTINEL_TEST_PHASE5_CONFIG"] = os.environ["SENTINEL_TEST_PHASE5_CONFIG"]
        environment["SENTINEL_TEST_PHASE5_WORKFLOW_EVIDENCE"] = str(output / "granite-private.json")
    environment.update(
        {
            "SENTINEL_DATABASE_URL": environment["SENTINEL_TEST_DATABASE_URL"],
            "SENTINEL_ENVIRONMENT": "test",
            "SENTINEL_EXTERNAL_EFFECT_MODE": "simulate",
            "LANGGRAPH_STRICT_MSGPACK": "true",
            "PYTHONUTF8": "1",
            "TEMP": str(output / "tmp"),
            "TMP": str(output / "tmp"),
            "TMPDIR": str(output / "tmp"),
            "MYPY_CACHE_DIR": str(output / "mypy-cache"),
            "RUFF_CACHE_DIR": str(output / "ruff-cache"),
        }
    )
    (output / "tmp").mkdir()
    write_json(output / "preflight.json", frozen)
    python = [sys.executable, "-B", "-m"]
    checks = [
        ("ruff", [*python, "ruff", "check", "."]),
        ("format", [*python, "ruff", "format", "--check", "."]),
        ("mypy", [*python, "mypy", "--strict", "src"]),
        (
            "tool-mypy",
            [
                *python,
                "mypy",
                "--strict",
                "tools/phase6_acceptance.py",
                "tools/phase6_observe.py",
                "tools/phase6_metrics.py",
            ],
        ),
        ("migration", [*python, "sentinelward", "db", "upgrade"]),
        ("checkpointer", [*python, "sentinelward", "db", "init-checkpointer"]),
    ]
    results = []
    for name, command in checks:
        result = run_check(name, command, output, environment)
        results.append(result)
        if name in {"migration", "checkpointer"} and result["status"] != "PASS":
            break
    counts: dict[str, Any] = {"status": "BLOCKED", "reason": "database setup failed"}
    if all(r["status"] == "PASS" for r in results if r["name"] in {"migration", "checkpointer"}):
        result = run_check(
            "pytest",
            [
                *python,
                "pytest",
                "-q",
                "--tb=short",
                f"--basetemp={output / 'pytest-temp'}",
                "-o",
                f"cache_dir={output / 'pytest-cache'}",
                f"--junitxml={output / 'pytest.xml'}",
            ],
            output,
            environment,
        )
        results.append(result)
        if (output / "pytest.xml").exists():
            counts = junit_summary(output / "pytest.xml", granite_required=granite)
    after = preflight(c1)
    status = "PASS"
    source_unchanged = frozen["source_tree_sha256"] == after["source_tree_sha256"]
    if (
        after["status"] != "PASS"
        or not source_unchanged
        or any(r["status"] == "FAIL" for r in results)
    ):
        status = "FAIL"
    elif counts["status"] != "PASS":
        status = counts["status"]
    summary = {
        "schema_version": 1,
        "profile": "local-isolated",
        "status": status,
        "scope": "Local software and isolated integrations; not connected team acceptance",
        "tests": counts,
        "checks": results,
        "granite_enabled_for_checks": granite,
        "real_telegram": "NOT RUN",
        "connected_acceptance": "NOT RUN",
        "m6_unchanged": frozen["m6_sha256"] == after["m6_sha256"] == M6_SHA256,
        "source_unchanged_during_checks": source_unchanged,
        "before": frozen,
        "after": after,
    }
    write_json(output / "summary.json", summary)
    return summary


def evidence_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": "REPLACE_WITH_ACTUAL_RUN_ID",
        "granite_enabled": False,
        "real_telegram": "NOT RUN",
        "gates": {
            key: {"status": "NOT RUN", "reason": description, "evidence": []}
            for key, description in (CONNECTED_GATES | OPTIONAL_GATES).items()
        },
    }


def create_profile(output: Path, phase4: Path, database: str) -> dict[str, Any]:
    """Generate private fictional configuration, not a deployed backend or model profile."""
    from sentinelward.config import Settings
    from sentinelward.phase4_factory import Phase4Configuration
    from sentinelward.phase5_factory import Phase5Configuration

    phase4 = phase4.resolve()
    verify_environment(
        {"SENTINEL_TEST_DATABASE_URL": database, "SENTINEL_TEST_PHASE4_CONFIG": str(phase4)}
    )
    broker = Phase4Configuration.model_validate_json(phase4.read_bytes())
    credentials = json.loads((phase4.parent / "credentials.json").read_text("utf-8"))
    template = json.loads((ROOT / "fixtures/phase5-config.example.json").read_text("utf-8"))
    template["staff"].update(
        version="phase6-fictional-1",
        nurses=["staff:priya", "staff:ravi"],
        charge_nurse="staff:charge",
        valid_until=time.time_ns() // 1_000_000 + 86_400_000,
    )
    template["staff_credentials"] = [
        {
            "token": secrets.token_urlsafe(32),
            "principal": {
                "by": "staff:priya" if role == "nurse" else f"staff:{role}",
                "role": role,
            },
        }
        for role in ("it", "nurse", "doctor")
    ]
    Phase5Configuration.model_validate(template)
    contexts = {
        d.bed_id: {"episode_id": "template-" + d.bed_id, "device_id": d.device_id, "start_ts": 0}
        for d in broker.inventory
    }
    values = {
        "SENTINEL_ENVIRONMENT": "test",
        "SENTINEL_DATABASE_URL": database,
        "SENTINEL_TEST_DATABASE_URL": database,
        "SENTINEL_TEST_PHASE4_CONFIG": str(phase4),
        "SENTINEL_PHASE4_CONFIG_FILE": str(phase4),
        "SENTINEL_PHASE5_CONFIG_FILE": str(output / "phase5.json"),
        "SENTINEL_M6_CONTEXTS_FILE": str(output / "contexts.json"),
        "SENTINEL_M6_ENABLED": "true",
        "SENTINEL_DEMO_LIFECYCLE_ENABLED": "true",
        "SENTINEL_EXTERNAL_EFFECT_MODE": "simulate",
        "SENTINEL_MQTT_HOST": broker.broker.host,
        "SENTINEL_MQTT_PORT": str(broker.broker.port),
        "SENTINEL_MQTT_TLS": "false",
        "SENTINEL_MQTT_USERNAME": "p4-observer",
        "SENTINEL_MQTT_PASSWORD": credentials["p4-observer"],
        "SENTINEL_MQTT_CLIENT_ID": "phase6-isolated-" + secrets.token_hex(4),
        "SENTINEL_BACKEND_SERVICE_TOKEN": secrets.token_urlsafe(32),
        "SENTINEL_HTTP_HOST": "127.0.0.1",
        "SENTINEL_HTTP_PORT": "8088",
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "PHASE6_OBSERVER_PASSWORD": credentials["p4-observer"],
    }
    # Validate explicit values without leaking them or inheriting developer .env settings.
    settings_values: dict[str, Any] = {
        k.removeprefix("SENTINEL_").lower(): v
        for k, v in values.items()
        if k.startswith("SENTINEL_") and "TEST_" not in k
    }
    settings_values["_env_file"] = None
    Settings(**settings_values)
    write_json(output / "phase5.json", template)
    write_json(output / "contexts.json", contexts)
    (output / "environment.sh").write_text(
        "# Private generated isolated-test credentials. Do not commit.\n"
        + "\n".join(f"export {k}={shlex.quote(v)}" for k, v in values.items())
        + "\n",
        "utf-8",
    )
    (output / "environment.ps1").write_text(
        "# Private generated isolated-test credentials. Do not commit.\n"
        + "\n".join("$env:" + k + " = '" + v.replace("'", "''") + "'" for k, v in values.items())
        + "\n",
        "utf-8",
    )
    if os.name != "nt":
        output.chmod(0o700)
        for path in output.iterdir():
            path.chmod(0o600)
    return {
        "status": "PASS",
        "scope": "Private fictional template profile only; no services started",
        "writer_enabled": False,
        "actual_telegram": False,
    }


def check_snapshot(manifest: Path) -> dict[str, Any]:
    data = json.loads(manifest.read_text("utf-8"))
    if data.get("schema_version") != 1 or not data.get("files"):
        raise ValueError("invalid source manifest")
    seen: set[str] = set()
    for row in data["files"]:
        relative = Path(row["path"])
        target = (ROOT / relative).resolve()
        if relative.is_absolute() or ROOT not in target.parents or row["path"] in seen:
            raise ValueError("source manifest path is unsafe or duplicate")
        seen.add(row["path"])
        if not target.is_file() or digest(target) != row["sha256"]:
            raise ValueError("source file differs from original transfer manifest")
    return {
        "status": "PASS",
        "files_verified": len(seen),
        "original_commit": data["git_commit"],
        "scope": "Transferred file hashes only",
    }


def assess(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    if set(data) != {"schema_version", "run_id", "granite_enabled", "real_telegram", "gates"}:
        raise ValueError("unknown/missing connected evidence fields")
    if data["schema_version"] != 1 or not isinstance(data["granite_enabled"], bool):
        raise ValueError("invalid evidence version/profile")
    if data["real_telegram"] != "NOT RUN":
        raise ValueError("real Telegram is outside the approved scope")
    if not isinstance(data["run_id"], str) or not data["run_id"].strip():
        raise ValueError("run_id is required")
    expected = CONNECTED_GATES | OPTIONAL_GATES
    if not isinstance(data["gates"], dict) or set(data["gates"]) != set(expected):
        raise ValueError("all declared gates must be retained")
    statuses: dict[str, str] = {}
    for key, gate in data["gates"].items():
        if set(gate) != {"status", "reason", "evidence"} or gate["status"] not in STATUSES:
            raise ValueError(f"invalid gate: {key}")
        if not isinstance(gate["reason"], str) or not gate["reason"].strip():
            raise ValueError(f"gate reason required: {key}")
        if not isinstance(gate["evidence"], list):
            raise ValueError(f"evidence must be a list: {key}")
        for receipt in gate["evidence"]:
            if set(receipt) != {"path", "sha256"}:
                raise ValueError(f"invalid receipt: {key}")
            relative = Path(receipt["path"])
            resolved = (path.parent / relative).resolve()
            if relative.is_absolute() or path.parent.resolve() not in resolved.parents:
                raise ValueError("evidence path must stay inside the evidence directory")
            if not resolved.is_file() or digest(resolved) != receipt["sha256"]:
                raise ValueError(f"missing or changed evidence: {key}")
        if gate["status"] == "PASS" and not gate["evidence"]:
            raise ValueError(f"PASS needs retained evidence: {key}")
        statuses[key] = gate["status"]
    required = list(CONNECTED_GATES)
    if data["granite_enabled"]:
        required.append("granite_target")
    status = "FAIL" if any(statuses[k] == "FAIL" for k in required) else "PASS"
    if status != "FAIL" and any(statuses[k] != "PASS" for k in required):
        status = "BLOCKED"
    return {
        "schema_version": 1,
        "status": status,
        "run_id": data["run_id"],
        "gates": statuses,
        "verification_basis": (
            "Operator-reported outcomes with file integrity checks; not an independent remote audit"
        ),
        "real_telegram": "NOT RUN",
        "clinical_validation": False,
    }


def snapshot(output: Path) -> dict[str, Any]:
    """Package the current checkout, including authorized uncommitted source, not .git or data."""
    roots = {"src", "tests", "tools", "docs", "fixtures", "migrations", "deploy", ".github"}
    names = {
        "pyproject.toml",
        "uv.lock",
        "README.md",
        ".gitignore",
        ".gitattributes",
        ".python-version",
        "alembic.ini",
        ".env.example",
    }
    manifest = []
    paths = (
        subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    archive = output / "sentinelward-phase6-source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for relative in sorted(set(paths) - {""}):
            path = ROOT / relative
            parts = Path(relative).parts
            if parts[0] not in roots and relative not in names:
                continue
            if any(p.startswith(".env") and p != ".env.example" for p in parts):
                raise ValueError("environment file in snapshot scope")
            if path.is_symlink() or ROOT not in path.resolve().parents:
                raise ValueError("snapshot cannot include symlinks or paths outside checkout")
            if not path.is_file():
                raise ValueError("tracked file missing; inspect working tree before snapshot")
            if path.suffix.lower() in {".pem", ".key", ".gguf", ".pcap", ".pcapng"}:
                raise ValueError("private/generated artifact in snapshot scope")
            content = path.read_bytes()
            if any(
                line.startswith(b"-----BEGIN ") and b"PRIVATE KEY" in line
                for line in content.splitlines()
            ):
                raise ValueError("private-key marker in snapshot scope")
            bundle.add(path, arcname=relative, recursive=False)
            manifest.append({"path": relative, "sha256": digest(path), "size": len(content)})
    result = {
        "schema_version": 1,
        "git_commit": git("rev-parse", "HEAD"),
        "working_tree": git("status", "--short"),
        "files": manifest,
        "archive_sha256": digest(archive),
        "archive": archive.name,
        "warning": (
            "Review file list and scan for credentials before transfer; "
            "no credentials or datasets intended"
        ),
    }
    write_json(output / "source-manifest.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--c1-source", type=Path)
    run = commands.add_parser("verify")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--isolated-resources", action="store_true", required=True)
    run.add_argument("--granite", action="store_true")
    run.add_argument("--c1-source", type=Path)
    template = commands.add_parser("evidence-template")
    template.add_argument("--output", type=Path, required=True)
    connected = commands.add_parser("assess")
    connected.add_argument("--evidence", type=Path, required=True)
    package = commands.add_parser("snapshot")
    package.add_argument("--output", type=Path, required=True)
    imported = commands.add_parser("check-snapshot")
    imported.add_argument("--manifest", type=Path, required=True)
    profile = commands.add_parser("init-profile")
    profile.add_argument("--phase4", type=Path, required=True)
    profile.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "preflight":
            result = preflight(args.c1_source)
            if not result["python_supported"]:
                result["status"] = "FAIL"
        elif args.operation == "verify":
            result = verify(fresh_output(args.output), c1=args.c1_source, granite=args.granite)
        elif args.operation == "evidence-template":
            target = fresh_output(args.output)
            write_json(target / "connected-evidence.json", evidence_template())
            result = {"status": "NOT RUN", "scope": "Template only; no connected checks executed"}
        elif args.operation == "snapshot":
            if preflight()["status"] != "PASS":
                raise ValueError("frozen source check failed")
            result = snapshot(fresh_output(args.output)) | {"status": "PASS"}
        elif args.operation == "check-snapshot":
            result = check_snapshot(args.manifest)
        elif args.operation == "init-profile":
            result = create_profile(
                fresh_output(args.output),
                args.phase4,
                os.environ.get("SENTINEL_TEST_DATABASE_URL", ""),
            )
        else:
            result = assess(args.evidence.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        status = result.get("status")
        raise SystemExit(0 if status == "PASS" else 2 if status == "FAIL" else 3)
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as exc:
        # Never echo exception text: URLs, credentials or private payloads may be present.
        print(
            f"PHASE6 FAILED: {type(exc).__name__}; inspect inputs and operator guide",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
