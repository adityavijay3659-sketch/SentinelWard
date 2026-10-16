# Phase 6 — verification and user-operated LinuxONE acceptance

Approved scope: verification only. Phase 7 remains a separate final handoff/submission phase.
The user creates and operates LinuxONE; this implementation does not remotely deploy or
claim access to the user's authenticated portal. Before the event's announced permitted
start on 17 October, LinuxONE practice uses throwaway scripts and dummy data only, with
no SentinelWard code. A date change alone is not authorization to start event work.

## Frozen starting point

Phase 5's last verified result was 229 passed, zero failures/skips; Ruff/strict mypy passed.
Its finite Granite acceptance and bounded load results do not prove target-host or team
acceptance. See [Phase 5 verification](phase-5-verification.md).

- Keep every current uncommitted file; no reset, push, merge or teammate-system edits.
- Production M6 remains `m6-research-0.3.4`: 900 seconds, 179 windows, 10-second windows,
  5-second evaluation step, cuff age 120 seconds, threshold 0.6. No calibration/training.
- C1 stays isolated and unmerged. Its research cycle and the 24-patient cohort stay closed.
- Missing assessment is not stable. Urgent outcomes retain precedence, including during
  containment and recording completion. Human/team output stays deterministic, one line,
  at most 160 characters. Reports are human-sent; A7 never reassigns staff.
- Templates are the default; real Telegram delivery is outside this approved test scope.

## Implementation and execution

1. Record source/import/configuration identity and optional external C1 hash. Produce an
   explicit source snapshot including uncommitted work, excluding .git, environments,
   credentials and datasets. Review its manifest before transfer.
2. Run the complete existing suite plus Phase 6 regressions using a dedicated loopback
   PostgreSQL database and Dynamic Security broker. Apply migrations/checkpointer, run
   lint/format/strict mypy and record exact JUnit counts. Required skipped checks block
   acceptance; disabled real Granite is an explicitly optional skip.
3. Exercise all eight locked verdicts, malformed/reordered/duplicate traffic, roles,
   pressure/urgency invariants, source-end races, stale scores/records, reset/restart,
   A1 escalation/ACK, containment/evidence/undo, A5 human workflow, A7/A8, prompt injection,
   generation cancellation/deadlines and persistence. Reuse existing tests rather than
   duplicating their implementations. Add meaningful verification-tool and 12-bed
   lifecycle boundary regressions.
4. Follow the [LinuxONE operator guide](phase-6-linuxone-operator-guide.md) to install an
   isolated instance after the event starts. The user performs all remote operations.
   Do not use a public service or shared team database for destructive checks.
5. Run the actual 12-bed, 20-minute scenario and reset/second-run smoke. Use a read-only
   observer and each owner's event logs, DB/API/WS/UI evidence. Record actual routes and
   latencies separately from injected local contract fixtures.
6. Assess operator-supplied connected evidence. Preserve PASS/FAIL/BLOCKED/NOT RUN per
   owner boundary. File hashes prove evidence integrity, not the truth of assertions.

## Interfaces and evidence

No runtime API, MQTT envelope, model configuration or scoring changes are introduced.
New tooling is source-checkout-only:

- `python -m tools.phase6_acceptance preflight|verify|snapshot|evidence-template|assess`
- `init-profile` generates private fictional template settings; `check-snapshot` verifies
  the transferred files against the local source manifest.
- `python -m tools.phase6_metrics` verifies capture hashes and summarizes per-bed source
  coverage, distinct M6 windows and receipt/probe latency against actual producer event logs.
- `python -m tools.phase6_observe --config <private-json> --output <fresh-private-directory>`
- [Scenario](../fixtures/phase6-scenario.json) and
  [observer configuration](../fixtures/phase6-observer.example.json) describe diagnostic
  inputs, not new MQTT message types. Verdict names use the existing `LOOSE_SENSOR` and
  `DEVICE_ATTACK` values; narrative "network attack" is not a new verdict.

Private outputs contain JUnit/logs, before/after hashes, source manifest, observation
metadata and operator evidence. Observer captures hashes, identities, labels and timestamps,
not waveform arrays, human prose or credentials. Its PASS means observation completed,
not that the system passed. Keep raw private logs out of Git and review before sharing.

## Gates and defaults

Local verification requires all critical checks passing, no required skips, unchanged
protected hashes and preserved existing work. No optional model fallback is counted as
strict Granite generation success. Templates may pass resilience checks independently.

Connected acceptance requires actual owner components and retained evidence for identity,
trust/ACLs, all routes, stale rejection, offline/urgent behavior, A1, A2–A4, narratives,
fault recovery, real-time scenario, second run and full-stack resource measurements.
Granite target acceptance is additionally required only when enabled. Real phone delivery
remains NOT RUN, so this phase cannot claim the historical live-phone gate is closed.

The frozen M6 cannot be forced to meet historical drift targets: no combined executions
were observed on the audited cohort, and Beds 3/4/7 have only 330/330/330 seconds respectively
from their declared admission to completion. Other beds' longer recording time is only
necessary, not sufficient, for readiness. Record honest coverage and limitations.

Finish labels:

- **LOCAL VERIFICATION COMPLETE — CONNECTED ACCEPTANCE PENDING** when only local proof exists.
- **PHASE 6 CONNECTED VERIFICATION COMPLETE (TELEGRAM SIMULATED)** only after actual target
  evidence passes. This is not clinical validation or complete live-phone acceptance.

Missing source assets, unknown contracts or unavailable owner components stay explicit
blockers; no patient replacement or fabricated source/latency results. Fix only demonstrated
in-scope integration defects with regression tests. Failed optional features stay disabled.
