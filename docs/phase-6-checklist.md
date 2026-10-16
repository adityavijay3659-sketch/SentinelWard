# Phase 6 acceptance checklist and ownership

Use [the approved plan](phase-6-plan.md) and
[the operator guide](phase-6-linuxone-operator-guide.md). The final results belong in
[verification](phase-6-verification.md). Local fixture/adapter proof does not validate an
unavailable teammate component. Real Telegram is intentionally NOT RUN.

## Local regression coverage

| Requirement | Existing/new evidence surface | Limit |
|---|---|---|
| All eight locked verdict routes | `test_contracts`, `test_policy_router`, `test_phase4::test_all_eight_verdicts_have_declared_non_a1_effects` | Supplied fixtures validate automation; actual model verdict quality remains external |
| Duplicate/malformed/idempotent workflows | `test_engine_service`, `test_contracts`, `test_mqtt_adapter`, `test_mqtt_outbox` | Actual deployed ACL/configuration still needs inspection |
| A1 ladder/ACK/phone failure | `test_alerts`, `test_phase2_adapters`, `test_postgres_integration` | Fake Telegram only; no actual phone delivery |
| M6 safety/alignment/abstention | Existing unchanged `test_m6*` and `test_real_recording_integration` | Software evidence only; closed research cycle is not reopened |
| Run/reset/offline/source-end races | `test_demo_lifecycle`, `test_demo_lifecycle_postgres`, `test_phase6_scenario` | New 12-bed test exercises chronological boundary windows, not a full 20-minute replay |
| Stale-run rejection | `test_demo_integration_boundary`, `test_phase4`, `test_phase5_postgres` | Required real backend boundary remains external |
| Containment/evidence/undo/watch | `test_phase4`, `test_phase4_broker`, `test_phase4_postgres`, `test_phase4_e2e` | Real private broker; fixture policy and ports are explicitly isolated |
| Human A5/PDF/deadline/history | `test_phase5`, `test_phase5_boundaries`, `test_phase5_postgres` | Human attestation is not an actual regulator receipt or automatic send |
| A7/A8 facts, coverage, urgency | `test_phase5`, `test_phase5_boundaries`, `test_phase5_recovery` | Real source receipts and rendered UI still need owner evidence |
| Granite verification/cancellation/queue/fallback | `test_phase5_recovery`, `test_phase5_boundaries`, `test_phase5_granite` | Full-suite Granite test is fail-closed resilience, not strict generation acceptance |
| Runner cannot claim false success | `test_phase6_acceptance` | Operator assertions remain human-reviewed, not independently attested |
| Observer reads actual MQTT without raw payloads | `test_phase6_observer_broker` | Read-only observation is not current-state projection proof |
| Coverage/latency denominators and evidence integrity | `test_phase6_metrics` | Score-window receipt delay differs from source fault detection and UI latency |

The runner executes all test files, not just this shortlist. JUnit retains failures and
required skips. Do not add focused counts to the full-suite total. Synthetic trainer unit
fixtures do not update production models; no model-training command is part of Phase 6.

## Connected gates: fill with actual evidence

The `evidence-template` command retains every gate below. Each PASS must cite retained
files and their hashes, with an explanation tied to the case and run. The assessor checks
structure and file integrity; it cannot verify that a screenshot/log assertion is true.

| Gate | Owner / classification | Required evidence |
|---|---|---|
| Target identity and source snapshot | You; BROKER/DEPLOYMENT DEPENDENCY | Instance architecture/Python, manifest comparison, installed modules, UTC/clock state |
| Broker trust | Broker owner; BROKER/DEPLOYMENT DEPENDENCY | Actual deny-by-default ACL/TLS config, owner-specific publisher/subscriber access tests |
| All routes | Decision/model owners; OTHER MODEL/AGENT OWNER DEPENDENCY | Actual M1–M5/D outputs plus permitted action routing; fixture results labelled separately |
| Run identity and stale rejection | Backend; BACKEND DEPENDENCY | Run A delayed score/record rejected after run B before projections, decisions, WS/UI |
| Source lifecycle | Simulator; SIMULATOR DEPENDENCY | Admission/end events and fresh runs; no looping short recordings |
| Offline and last values | Backend/UI; BACKEND DEPENDENCY | DB, real API/WS and screen OFFLINE/last values/offline_since |
| Urgent precedence | Decision/backend/agents; OTHER MODEL/AGENT OWNER DEPENDENCY | BOTH/recording-end chronology; urgent alert remains active |
| Alert ladder and ACK | Backend/UI; BACKEND DEPENDENCY | Current actor/grant, one screen alert, timer/restart audit; simulated backup clearly marked |
| Containment/evidence/undo | Kartik; KARTIK DEPENDENCY | Scoped actual disable/session cleanup, evidence hash, failure and authorized exactly-once undo |
| Narrative public projection | Backend/UI; BACKEND DEPENDENCY | A5 edits/review/export/partial attestation; A7 boundary; A8 facts/urgent/provenance/current generation state |
| Failure/recovery | You and affected owners; BROKER/DEPLOYMENT DEPENDENCY | Owned-resource outage/restart traces; no duplicate action or false-success state |
| Twenty-minute scenario | Whole team; SIMULATOR DEPENDENCY | Declared assets, event logs, observer capture, actual component and UI evidence |
| Reset and second run | Every stateful owner; OTHER MODEL/AGENT OWNER DEPENDENCY | New contexts/no old runtime, preserved audit/history and sent records |
| Full-stack load | You and backend/model owners; BROKER/DEPLOYMENT DEPENDENCY | Counts/denominators, p50/p95/max, queues, CPU/RSS/memory and unobserved intervals |
| Optional target Granite | Deployment; BROKER/DEPLOYMENT DEPENDENCY | Approved compatible artifact, strict workflow/deadline/load evidence; otherwise disabled |

## Explicit remaining contract limitations

- Source completion uses the authenticated internal endpoint plus declared timers. There
  is no new MQTT source-end topic. Existing lifecycle semantics stay unchanged.
- Vitals/verdict wire messages do not carry run ID. Simulator/gateway binding and time/
  sequence context remain necessary; a missing run ID alone is not a stale verdict.
- Model scores use `extra.demo_run_id`; agent records use `data.run_id` and revision where
  required. Backend must reject old outputs before changing state, not just hide them in UI.
- Actual M6 assessment paths are `unavailable`, `cuff_gap_only`, `baseline_combined`.
  Descriptive "combined" in reports must not become a new runtime enum.
- Public API/WS projection and same-record replacement are backend-owned. The local
  reference routes cannot be relabelled as real backend acceptance.
- Human report-sent MQTT action naming remains a CONTRACT AMBIGUITY. Use the existing
  typed report attestation/audit; do not invent a new locked `ward/action.by` owner.
- Official demo source confirmations and historical M6 timing targets are not evidence
  that the frozen full baseline can run. Retain unavailable data and honest limitations.
- A5 automatic drafting in older scripts does not override the approved IT confirmation
  workflow. A report clock/audit/sent action is not meaningfully reversible by deletion.

Local code/checks can be complete with these external dependencies pending. Do not call
Phase 6 connected acceptance complete until the applicable actual gates pass. Phase 7
will prepare the final teammate handoff and submission package.
