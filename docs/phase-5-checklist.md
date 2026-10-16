# Phase 5 acceptance checklist

Status: local implementation and strict full-workflow Granite generation acceptance verified; deployment/team gates remain separate. See [verification](phase-5-verification.md), [final plan](phase-5-plan.md) and dated [source review](phase-5-source-review.md). A checked item describes local evidence only.

## Decisions and source contracts

- [x] Eight user choices locked before implementation.
- [x] Report field mapping and primary-source note pinned; missing fields explicit; applicability remains human-owned.
- [x] Staff/charge-nurse/shift profile, event-time role/routing provenance declared.
- [x] Trust/coverage ledger and suppression receipts; missing metrics remain unavailable.
- [x] Typed records, protected human commands and backend revision/role expectations documented.

## Shared safety and persistence

- [x] Typed source snapshots with hashes, provenance, interval and coverage.
- [x] Atomic PostgreSQL records/audit/actions/outbox; idempotency and restart recovery tested.
- [x] Generation outside lifecycle locks/transactions; stale and late jobs rejected.
- [x] Per-run history retained, including repeated cursor keys; new runs isolated.
- [x] Only fact count/predicate-kind codes enter the model; code binds all IDs/values. No PHI/contacts/secrets/raw signals.
- [x] Frozen M6/C1 hashes match; no algorithm/training changes.

## A5

- [x] Authenticated confirmation; distinct occurred/observed/noticed/confirmed times.
- [x] Six-hour anchor survives regeneration/restart; corrections require provenance/review.
- [x] All fields filled/flagged with provenance; incomplete evidence stays incomplete.
- [x] Human edits and revision-bound checklist protected.
- [x] PDF text/escaping/draft/demo/missing markers and revision/hash verified.
- [x] Human mark-sent attestation only; no send/receipt/compliance claim.
- [x] Compensation preserves clocks, human edits, sent revisions, evidence and audit.

## A7

- [x] Exact two-hour endpoints and >40 policy; 40/41 boundary tested.
- [x] Unique alert-recipient events; message retries/acknowledgements excluded by identity.
- [x] Escalation, unknown roster/doctor exclusion and routed channel provenance handled.
- [x] Minute schedule, overload/recovery and charge-nurse warning persisted.
- [x] No automatic reassignment or staffing advice.

## A8

- [x] Configured shift/on-demand and T+19:00 triggers; timezone/DST tests.
- [x] Counts versus state, interval union/conflict/unknown coverage and known source exclusions.
- [x] Explicit suppression receipts only; absent source remains unavailable.
- [x] Urgent/current-state section independent of Granite and refreshed from durable A1.
- [x] Facts, interval, source revisions, coverage and provenance retained.

## Granite and final verification

- [x] Pinned artifact/build/chat template and actual server schema probe.
- [x] Fact-linked composition binds each ID/predicate exactly once; values/units/time are inserted from its snapshot.
- [x] Timeout/outage/invalid/stale/queue overflow/late-result fallback tested.
- [x] Predeclared 30-case engineering evaluation: 30 accepted, zero unsupported accepted outputs in this controlled format.
- [x] Larger actual workflow rejection/timeout retained and reported separately.
- [x] Strict full-workflow local gate: six actual coordinator cases repeated three times plus two scheduled cases, 20 accepted with no fallback.
- [x] Failed refinement preserves revision/PDF; disabled writer creates no job; reset/edit/undo cancel obsolete inference.
- [x] Capacity measured on pinned tokenizer; complete 42-fact composition fits unchanged 512-token budget.
- [x] Streaming cancellation verified against the actual owned server; complete/stop/DONE validation rejects unfinished output.
- [x] Final bounded 12-bed lifecycle/ledger comparison passed at +8.82%; earlier failed comparisons retained, full live scope remains external.
- [ ] Deployment resource/latency and whole-team ingress gate. See verification for local contention measurements and profile limits.
- [x] Real broker/PostgreSQL lifecycle, local API/auth/revision and restart evidence.
- [x] Full pytest/static/migration/build/installed package/actual CLI checks; exact evidence in verification report.
- [x] Frozen hashes verified; private credentials, logs, raw data and models kept outside Git.
- [x] Contracts, examples, runbook, verification and team smoke-test procedure created.

## Team acceptance (external)

- [ ] Actual backend API/WS/roles/edit/mark-sent integration.
- [ ] Antara S8/S10 current/missing/urgent/generation-provenance displays.
- [ ] Actual roster, coverage and suppression-source acceptance.
- [ ] LinuxONE model/build/byte-order/resources and measured latency.
- [ ] End-to-end team demo and feature-freeze acceptance.

No push, merge or deployment is authorized by this implementation request. Do not mark team dependencies or Granite acceptance complete from a local fixture/template.
