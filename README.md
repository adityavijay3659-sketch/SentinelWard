# SentinelWard

SentinelWard is Team TessNova's IBM Z Datathon 2026 project: a real-time system that distinguishes a genuine patient emergency, a faulty or drifting sensor, and tampered monitor data while keeping every patient visible.

## Repository status

This repository contains the Phase 1–5 local implementation and Phase 6 verification
tools. The latest implementation branch is `phase/6-verification`, building on
`phase/5-narrative-agents`. The latest full local run passed 245 tests with zero failures
or skips; LinuxONE and connected-team acceptance remain pending. Phase 7 stays separate.
Production M6 is frozen; C1 remains isolated and unmerged.
Local checks and live/team acceptance gates are recorded separately in each phase checklist.

- Phase 1 implementation began on **8 October 2026** at Aditya's explicit direction.
- The initial Phase 0 commit was pushed after Aditya's approval; commit or push subsequent changes only on explicit request.
- Toy learning exercises must remain outside this repository and must not use SentinelWard logic or data.
- The locked team contract is `Doc 00 v1.1`; wire payloads retain `v=1`. Files here explain and validate it; they do not silently replace it.

## Phase 2 quick start

```powershell
uv sync --frozen --extra dev
uv run sentinelward validate-config
uv run pytest
```

Database-backed verification additionally requires PostgreSQL:

```powershell
$env:SENTINEL_DATABASE_URL = "postgresql://user@host:5432/sentinelward"
uv run sentinelward db upgrade
uv run sentinelward db init-checkpointer
uv run sentinelward smoke-test
```

## Phase 3 quick start

The following commands document the historical research harness. The current M6
research cycle is closed; use the Phase 6 operator guide for verification without new
calibration, training or algorithm experiments.

```powershell
uv run sentinelward m6 demo --report D:/m6-synthetic-report.json
uv run sentinelward m6 replay --manifest data/m6-case.json --view team
```

The demo uses synthetic waveforms and records measured delay and safety checks.
Real-data calibration and the reviewed hypotension safety gate remain pending.
The [real-data experiment](docs/real-data-verification-2026-10-09.md) downloaded
12 subjects, trained/tested an offline regression, and found that the runtime
baseline did not become ready on this subset. Research weights are not deployed.
The [M6-only revalidation](docs/m6-revalidation-2026-10-09.md) fixes cold-start
gap assessment and evaluates controlled drift on 12 new subjects. Offline MAE
is 8.55 versus 10.10 mmHg on the same held-out windows; full baseline readiness
remains 0/12 and clinical deployment is not approved.
The [M6 repair evidence](docs/m6-repairs-2026-10-10.md) documents pressure-guard,
baseline continuity, abstention/evaluation and replay-clock fixes, plus dataset
preflight, bounded cohort configuration and reproducible local verification.
For live research ingestion, supply an episode/device map and enable M6 explicitly;
see [Phase 3 operation and handoff](docs/phase-3-implementation.md).
Human output is one line of at most 160 characters; machine JSON preserves all fields.

## Aditya's ownership

- Shared LangGraph agent engine, policy guard, persistence, action audit and undo coordination.
- A1 alert ladder with Antra.
- A5 CERT-In draft, A6 biomed tickets, A7 workload watch and A8 shift briefing.
- Integration host for Kartik's A2 containment, A3 evidence and A4 fleet-hunt handlers.
- IBM Granite text generation with deterministic template fallback.
- M6 blood-pressure drift watcher, reviewed by Aditya Singhal.
- A9 playbook learning as design-only work.

## Phase 0 navigation

- [Architecture](docs/architecture.md)
- [Canonical contracts and naming](docs/contracts.md)
- [One-line output compatibility](docs/one-line-output.md)
- [Agent registry and permissions](docs/agent-registry.md)
- [Team handoffs](docs/handoffs.md)
- [M6 design](docs/m6-design.md)
- [Failure and security policy](docs/failure-policy.md)
- [Implementation phases](docs/implementation-phases.md)
- [Current status of every phase](docs/phases-status.md)
- [Local environment inventory](docs/local-environment.md)
- [Phase 0 verification evidence](docs/phase-0-evidence.md)
- [Phase 0 completion checklist](docs/phase-0-checklist.md)
- [Phase 1 architecture](docs/phase-1-architecture.md)
- [Phase 1 implementation and handoffs](docs/phase-1-implementation.md)
- [Phase 1 completion checklist](docs/phase-1-checklist.md)
- [Phase 2 alert architecture](docs/phase-2-architecture.md)
- [Phase 2 completion checklist](docs/phase-2-checklist.md)
- [Phase 3 plan](docs/phase-3-plan.md)
- [Phase 3 implementation and handoff](docs/phase-3-implementation.md)
- [Phase 3 completion checklist](docs/phase-3-checklist.md)
- [Current verification evidence](docs/phase-3-verification.md)
- [Doc 00 v1.1 demo lifecycle integration](docs/demo-v1.1-integration.md)
- [Phase 4 implementation and local acceptance](docs/phase-4-plan.md)
- [Phase 4 contracts and isolated runbook](docs/phase-4-runbook.md)
- [Phase 5 final plan](docs/phase-5-plan.md)
- [Phase 5 contracts](docs/phase-5-contracts.md)
- [Phase 5 operation and team smoke test](docs/phase-5-runbook.md)
- [Phase 5 measured verification and limitations](docs/phase-5-verification.md)
- [Phase 6 verification plan](docs/phase-6-plan.md)
- [Phase 6 LinuxONE instructions for the operator](docs/phase-6-linuxone-operator-guide.md)
- [Phase 6 coverage and external-owner checklist](docs/phase-6-checklist.md)
- [Phase 6 measured verification](docs/phase-6-verification.md)
- [Detailed new-chat continuation handoff](docs/new-chat-handoff-2026-10-09.txt)
- [Publication verification](docs/publication-verification-2026-10-09.md)
- [Operations runbook](docs/runbook.md)
- [Complete Phase 0–1 technical summary](docs/phases-0-1-complete-summary.md)
- [Contract examples](fixtures/contract-examples.json)

## Non-negotiable safety rules

1. A patient is never displayed as blank.
2. Suspected tampering never cancels an emergency alert.
3. Every automatic action is logged and reversible where reversal is meaningful.
4. Automation never controls treatment, medication, pumps or ventilators.
5. Official reports are drafted automatically but sent only by a person.
6. SentinelWard listens to monitor data and never writes commands back to a monitor.
