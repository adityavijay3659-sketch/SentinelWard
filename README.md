# SentinelWard

SentinelWard is Team TessNova's IBM Z Datathon 2026 project: a real-time system that distinguishes a genuine patient emergency, a faulty or drifting sensor, and tampered monitor data while keeping every patient visible.

## Repository status

This repository contains the **Phase 1 foundation implementation** on the
`phase/1-foundation` branch.

- Phase 1 implementation began on **8 October 2026** at Aditya's explicit direction.
- The initial Phase 0 commit was pushed after Aditya's approval; commit or push subsequent changes only on explicit request.
- Toy learning exercises must remain outside this repository and must not use SentinelWard logic or data.
- The locked team contract remains `Doc 00 v1`. Files here explain and validate it; they do not silently replace it.

## Phase 1 quick start

```powershell
uv sync --extra dev
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
- [Local environment inventory](docs/local-environment.md)
- [Phase 0 verification evidence](docs/phase-0-evidence.md)
- [Phase 0 completion checklist](docs/phase-0-checklist.md)
- [Phase 1 architecture](docs/phase-1-architecture.md)
- [Phase 1 implementation and handoffs](docs/phase-1-implementation.md)
- [Phase 1 completion checklist](docs/phase-1-checklist.md)
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
