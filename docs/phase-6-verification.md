# Phase 6 local verification — 16 October 2026

**LOCAL VERIFICATION COMPLETE — CONNECTED ACCEPTANCE PENDING.**

Phase 6 acceptance tooling and the user-operated LinuxONE instructions are implemented.
No LinuxONE instance was created, accessed or deployed by this work. The actual team
backend/simulator/models/UI and real target performance remain unverified. Real Telegram
is intentionally NOT RUN. Phase 7 handoff/submission remains separate.

## Implemented

- Source-checkout acceptance runner: frozen source/import/config checks, dependency inventory,
  before/after code/fixture fingerprints, isolated-resource guards, migrations/checkpointer,
  full checks, JUnit error/skip accounting and private evidence.
- Reviewed-source snapshot tooling includes existing uncommitted Phase 5/6 work without
  .git, environments, model assets, datasets or private runtime profiles. A transfer manifest
  verifies each file independently of the target's local-only Git metadata.
- Private fictional profile generator creates matching contexts, expiring roster, bound staff
  credentials, service/observer secrets and shell/PowerShell environment files. Templates
  remain default; it starts no services and prints no credentials.
- Read-only MQTT/HTTP observer keeps hashes and selected wire metadata, never raw waveforms
  or message prose. It records queue drops/disconnections, bounded probes and Linux process
  resource counters. Windows resource measurements are explicitly unavailable.
- Metrics summarizer verifies capture hashes and producer run identity, preserves missing
  denominators, deduplicates M6 window receipts and separates assessment paths/unavailable
  labels. Score-window receipt delay and HTTP latency are not fault detection/UI latency.
- Connected evidence checklist retains every owner gate. Missing evidence blocks success;
  matching hashes establish file integrity only. Operator assertions still require review.
- The chronological twelve-bed regression checks admissions, real frozen-M6 first scoring
  windows, known source-end boundaries, last readings, no silence scores, idempotent reset,
  retained history, new episode IDs and stale-frame rejection. It is a boundary fixture,
  **not** an uninterrupted twenty-minute whole-team replay or new M6 experiment.

## Measured checks

Executed with `D:\SentinelWard-Phase2-Venv\Scripts\python.exe`, Python 3.12.14, using a new
dedicated `sentinel_phase6_local_20261016` PostgreSQL database, an owned loopback Mosquitto
Dynamic Security broker, existing local VitalDB fixtures and the existing pinned Granite.
Private lab/scratch/results are under `D:\SentinelWard-Phase6`.

| Check | Result |
|---|---|
| Full pytest | **245 passed, 0 failed, 0 skipped**, CLI 225.85 s; JUnit 225.836 s |
| New Phase 6 tests within that total | 16 passed; not added again to the full count |
| Ruff lint | PASS |
| Ruff formatting | PASS |
| Strict mypy, application | PASS, 59 source files |
| Strict mypy, new tools | PASS, 3 source files |
| Fresh database migrations | PASS, 0001 through 0007 |
| Checkpointer initialization | PASS |
| PostgreSQL lifecycle/restart/history tests | PASS, included in full suite |
| Actual new observer over private MQTT | PASS, included in full suite |
| Actual CLI startup with generated template profile | PASS; owned child stopped |
| Internal access, no bearer / valid bearer | 401 / 200 |
| Reference nurse briefing read | 200 |
| Unfilled connected evidence assessment | BLOCKED, expected exit 3; no false connected success |

No existing production tests were edited. Phase 5's previous 229 cases remain in the full
suite. Existing synthetic trainer unit fixtures do not update production artifacts; no
research training, dataset download/replacement, model experiment or tuning command ran.

The first focused attempt used the protected default Windows pytest temp directory and had
seven fixture setup permission errors. Its five passing cases were not a healthy suite.
Fresh D: scratch resolved that environment issue; focused checks and the full suite then
passed. Failed attempts are not counted as additional passing evidence. The interrupted
verification run resumed without duplicate execution. Its elapsed mypy wall time spans
the interruption and is not a performance benchmark.

The actual Granite test exercised accepted report and briefing jobs. Its controlled logical
clock does not measure model latency; it is a fail-closed workflow test, not a repetition
of the strict 20-case generation acceptance. Phase 5's strict acceptance remains historical
local evidence; LinuxONE model/deadline/full-stack load acceptance is still NOT RUN.

## Frozen implementation and version distinction

Python imports `C:\Users\Aditya\SentinelWard\src\sentinelward\m6.py`, identifying itself as
`m6-research-0.3.4`. Project metadata in `pyproject.toml` is 0.3.4. The development interpreter's
installed distribution metadata still says **0.2.0**; that historical mismatch is recorded,
not silently repaired or used to infer an old imported scorer. Runtime source/configuration
and hashes were checked explicitly. A fresh target installation must verify its own identity.

- M6 SHA-256: `4b1c9084935a8d253fd00d67f9011c464281d79928cbd9a2f4d7c90d2b66c4c7`.
- Isolated C1 SHA-256: `ede527738073fb8774406773da4970a8d9ee034caf78fe185f5d2351ecafad9f`.
- Code/fixture/lock fingerprint: `7d6aed26d897be86fe036785ca823bb35be21d8ba862914ea345b335d31e4beb`,
  138 files, unchanged throughout the checks. Documentation was completed separately.
- Configuration remains 900 seconds / 179 windows, cuff freshness 120 seconds, drift 0.6;
  all other production scoring/guard/feature behavior is unchanged.

At this verification checkpoint, Phase 5/6 changes were uncommitted on
`phase/5-narrative-agents`, based on `e01e090`; no push, merge or deployment had occurred.
Subsequent publication state is recorded in [current phase status](phases-status.md).
C1 is not in the production/source-transfer package.

## What remains external

| Item | Classification |
|---|---|
| Acceptance tools, fixtures, local checks and operator instructions | MY CODE COMPLETE |
| Actual API/WS/UI projection, roster/session grants, stale-score/record rejection | BACKEND DEPENDENCY |
| Actual scenario assets, timing, source completion, producer event logs | SIMULATOR DEPENDENCY |
| Actual A2/A3/A4 controls, evidence/session cleanup and undo | KARTIK DEPENDENCY |
| Actual M1–M5/D outputs, rendered frontend and state reset | OTHER MODEL/AGENT OWNER DEPENDENCY |
| User-operated instance, s390x install, ACL/TLS, clocks, isolated failure runs and load | BROKER/DEPLOYMENT DEPENDENCY |
| Human report-sent MQTT action naming | CONTRACT AMBIGUITY; retain existing safe typed attestation |

The user performs LinuxONE execution after the event's announced permitted start. Before
then, only throwaway practice scripts and dummy data may run there. No actual phone send
is authorized. Keep the local repository authoritative; preserve permitted evidence locally
before server teardown and mark evidence unavailable if export is prohibited.

Use [operator steps](phase-6-linuxone-operator-guide.md),
[coverage/owner checklist](phase-6-checklist.md), [plan](phase-6-plan.md), and
[sanitized machine summary](phase-6-evaluation.json). An actual connected PASS requires
retained owner evidence; no desire to improve the demo justifies touching M6 again.
