# Phase 4 completion checklist

Local implementation is complete on `phase/4-agent-integration`, from published checkpoint `905235d`. This ledger uses the revised decisions confirmed by Aditya. See the [verification report](phase-4-verification.md), [contracts](phase-4-integration-contracts.md), [runbook](phase-4-runbook.md) and historical [source review](phase-4-source-review.md).

## Local acceptance

- [x] Replaceable A2–A4 handlers operate against real isolated Mosquitto, filesystem evidence and PostgreSQL.
- [x] All eight verdict routes are tested; A1 urgency survives security-agent failures.
- [x] Automatic containment requires an explicit policy. The lab's 0.8 fixture is not approved production policy.
- [x] Disable, session cleanup and untrusted projection have independent durable outcomes.
- [x] Real broker tests prove rejected reconnect and removal of persistent subscriptions and an unacknowledged QoS 1 delivery.
- [x] Isolate/undo require trusted IT identity, approval, target, run and expiry. An old undo cannot reverse a newer containment.
- [x] Effects reconcile after uncertain replies and restart; duplicate delivery cannot invent a second business effect.
- [x] Actions, audit, records and outbox are durable; compensation receipts preserve original records.
- [x] A3 freezes actual artifacts, checks hashes, retains missing context and appends revisioned timelines.
- [x] A4 maintains independent one-hour same-model watch leases, expiry and owner-specific undo; it never isolates peers.
- [x] A6 merges faults into one unresolved device ticket, counts distinct loose episodes and preserves human closure.
- [x] Reference backend validates current run and monotonic revisions; human edits require the biomed role.
- [x] Run/reset clear active agent state and scoped A1 timers while preserving history and isolation.
- [x] A lifecycle gate prevents in-flight old workflows from entering a new run.
- [x] Known completion projects offline state and last values without scoring silence.
- [x] Output checks preserve deterministic bounded text and full machine records.
- [x] Production M6 and isolated C1 remain unchanged.

Exact test counts and command results are recorded in the verification report. Local evidence does not validate another owner's deployed system.

## Deployment acceptance still required

- [ ] Lead/backend: accept internal authorization, run binding, record revision and trust/offline projection contracts; expose public API/WebSocket state.
- [ ] Kartik: review/replace broker, evidence and fleet adapters with deployed capabilities; provide raw PCAP if required.
- [ ] Decision/model owners: approve containment policy and consume watch leases without undocumented threshold changes.
- [ ] Antara: show truthful pending/failed/unknown/undo/evidence/ticket state and role controls on S6/S7/S9/S11.
- [ ] Simulator/attack owners: connect run/reset, valid source contexts and completion notifications; reject old-run traffic.
- [ ] Deployment owner: inspect real ACLs, credentials, TLS, evidence access/retention and single-worker/scheduler-leader operation.
- [ ] Team: execute the [lifecycle smoke test](demo-v1.1-team-smoke-test.md) plus B05-style containment/undo, B07-style BOTH and B08-style ticket checks with MQTT, DB, API, logs and screen evidence.

No deployed UI, PCAP capture, LinuxONE runtime, twelve-bed performance or clinical validation is claimed. Phase 4 local completion and team deployment acceptance are separate gates. This work does not authorize a push, merge, deployment or teammate message.
