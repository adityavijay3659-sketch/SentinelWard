# Phase 5 integration contracts

This is the implemented local boundary, not confirmation of deployed backend or screen integration. MQTT v1 envelopes are unchanged. The source of truth for field names, limits and enum values is [phase5_contracts.py](../src/sentinelward/phase5_contracts.py); HTTP routing is [phase5_api.py](../src/sentinelward/phase5_api.py).

## Identity, ownership and authority

| Boundary | Producer → consumer | Required identity / effect |
| --- | --- | --- |
| `ward/demo/control` | trusted backend → existing lifecycle, Phase 4, Phase 5 | Existing v1 `run/reset`, `run_id`, `ts`, optional `start_at_s`. Reset retires jobs/pending run outbox; retains history and notice anchors. |
| Durable A1 alert callback | actual A1 store/publisher → A7/A8 | Reads stored `demo_run_id`, recipients, roster/version, active/priority and timestamps. MQTT-only reconstructed role/run claims are insufficient. |
| `ward/request` | backend → owning agent | Existing actions only. A1 ack/escalate and A2 isolation routing stay unchanged. Phase 5 consumes only undo targeting its own stored action, with a trusted exact-target IT grant. |
| `ward/record` report | A5 → backend | Existing `v,type,ts,kind,record_id,by,data`; `by=A5`, `kind=report`. |
| `ward/record` workload | A7 → backend | Same envelope; `by=A7`, `kind=workload`. |
| `ward/record` briefing | A8 → backend | Same envelope; `by=A8`, `kind=briefing`. |
| `ward/action` | owner A5/A7/A8 → audit/backend | Only registered owner capabilities: draft_report/start_clock, warn_workload, write_briefing. Approved human identity is `approved_by`; every effect is journalled atomically. |
| `ward/bed/<bed_id>/score/M6` | frozen M6 → backend | Unchanged. Neither report nor briefing generation consumes requests as model input. |

All Phase 5 record `data` contains `schema_version=1`, `run_id`, positive `revision`, and `as_of` in UTC epoch milliseconds. Backend must reject retired-run data and equal/older revisions for the same record ID. It must not replace current-run state with a delayed old-run record. QoS1 redelivery is expected; record IDs/revisions are the replacement boundary. Local `RecordProjection` tests this rule; the real public API/WS implementation remains backend-owned.

The locked action envelope accepts agent IDs in `by`, despite the project describing a human `mark_report_sent` action. This implementation preserves that envelope: human send attestations live in the typed report's `sent` object and audit, while A5 publishes a draft-record update with `approved_by`. It never emits a falsely agent-authored send action. Team agreement is needed if a separate human MQTT action is required.

## Record data

| Kind | Implemented fields beyond the common header |
| --- | --- |
| Report | `incident_id,status,occurred_ts,observed_ts,noticed_ts,confirmed_ts,provisional_notice,notice_provenance,deadline_ts,fields,missing_fields,evidence,narrative,snapshot_id,human_edited,checklist,checked_revision,sent,pdf,policy_note` |
| Workload | `since,threshold=40,comparator=">",basis="distinct_screen_routed_alerts",nurses,unassigned_events,charge_nurse,notification,roster_version` |
| Briefing | `since,scope,snapshot_id,facts,narrative,urgent,status` |

Report fields have `value,status,source`; every supported field is present or explicitly missing. A human edit invalidates PDF/checklist approval and uses compare-and-swap `expected_revision`. Material edits require a separate review step. `sent` records human attestation, exact submitted revision/hash, missing-field follow-up and `receipt_verified=false`; it does not claim actual transport.

Facts bind predicate, subject, value, unit, status, source, revision and interval. Snapshot hash includes scope and source versions. Narrative has generator/template/human provenance, model/build/hash identity, prompt/phrase versions, verifier result, fallback reason and elapsed time. Human prose is explicitly `verified=false`. The deterministic renderer inserts all values; model output cannot introduce a new fact or omit a required one. The urgent array and current urgent API state do not depend on model text.

## Authenticated internal HTTP

Every path below starts with `/internal/v1/phase5`. A backend service bearer authenticates the service. The backend must authenticate its human session and register a server-attested grant; a client-supplied `by` or role is not proof of authority.

| Method/path | Typed body / result |
| --- | --- |
| POST `/authorizations` | `HumanGrant`: request_id, principal `{by,role}`, run_id, action, target_id, expires_ts. Same ID/different content rejected. |
| GET `/status` | Current runtime, records, jobs, urgent state; no writer credentials. |
| POST `/incidents/{id}/confirm-report` | `ConfirmReport`: common command plus optional noticed_ts/notice_reason. IT only. |
| PATCH `/reports/{id}` | `EditReport`: common command plus fields/description/checklist booleans/notice correction. IT only, expected revision. |
| GET `/reports/{id}/pdf` | application/pdf; X-Document-SHA256 and X-Report-Revision headers. |
| POST `/reports/{id}/mark-sent` | `MarkSent`: common command plus document_hash, sent_ts, partial, acknowledged_missing, note. IT only. |
| POST `/briefings` | `GenerateBriefing`: common command plus optional since. Nurse/doctor only; causal current-run interval. |
| POST `/actions/{id}/undo` | `HumanCommand`, IT only; owner-resolved compensation. Clock/sent/human-edited artifacts cannot be undone. |
| POST `/coverage` | `CoverageReceipt`: receipt_id,run_id,bed_id,start_ts,end_ts,state,source. Explicit interval; conflicting receipts rejected. |
| POST `/suppression` | `SuppressionReceipt`: receipt_id,run_id,bed_id,alarm_id,ts,decision_id,source. Actual source receipt only; duplicates deduplicated. |

Common command: `v=1,request_id,by,run_id,ts,expected_revision` (revision default 0, meaningful for updates). Grant action values are `confirm_report,edit_report,mark_report_sent,briefing,undo`; target is exact incident/report/action ID or `WARD` for a briefing. Unknown fields/enums/versions fail schema validation (422). Authentication fails 401; role/grant mismatch 403; missing target 404; stale/conflicting state 409. Exact completed command retries return stored receipts, even after grant expiry, only for identical content in the same active run.

For locked MQTT undo, the coordinator resolves the current generated target revision while the lifecycle gate is held; human-edited/sent artifacts remain protected. Direct HTTP undo requires the caller's expected revision. A7 compensation retires a warning action, never rewrites measured workload or implies reassignment.

## Local reference API

Staff tokens are bound to principals on the server in the private `staff_credentials` profile. No configured staff credentials means no public staff access. IT: POST `/api/incidents/{id}/report`; GET/PATCH `/api/reports/{id}`; GET `/api/reports/{id}/pdf`; POST `/api/reports/{id}/mark-sent`. Nurse/doctor: GET `/api/briefing?since=<epoch_ms>`, POST `/api/briefing/generate`, GET `/api/workload?hours=2`. Other hour policies are rejected. Existing `/api/actions` includes Phase 5 canonical messages with owner/run/undo metadata. All are labelled `reference_only`; no teammate backend was modified.

## Measurement definitions

- A7: distinct `(run_id,alert_id,staff_id)` first-screen-routing observations in `(as_of-2h,as_of]`. Escalation to a new nurse counts once. Retry, acknowledgement, message edit and phone backup do not create another count. Routing is not proof of delivery/read. Unknown roles stay unassigned; roster expiry marks coverage partial. Overload is strictly >40.
- A8: events use `[since,as_of)`; current open tickets/urgent/untrusted/offline are separate current-state facts. Blind Time means measured untrusted time inside the declared recording interval. Before known admission and after explicit/known completion are excluded and reported as `*_outside_recording_interval`. Unknown/contradictory coverage remains `*_unknown_coverage`, never healthy or blind by assumption. Overlapping intervals are unioned per bed.
- Local trusted intervals require fresh frames plus an explicit recent decision with `last_trusted_ts=null`; freshness expires. No physiology or silence is used to invent an attack/offline outcome. Conflicting source intervals cannot count as trusted or blind.
- Recorded suppression is deduplicated by actual alarm/decision evidence. No receipts means unavailable, not zero alarms prevented or clinical benefit.

## Recovery contract additions — 16 October 2026

Model-only wire format `v=2` is `{v,order,wording}`. `order` is `source` or `reverse`; `wording` contains exactly one binary digit per source fact, selecting the existing plain/concise phrase. Code binds each digit to its source fact before applying order, expands to native v1 `Composition`, and independently verifies exact fact/predicate coverage again. Every required fact remains present. The prompt contains only fact count and predicate-kind codes, never source values, IDs, notes, contacts or raw signals. `prompt_version=phase5-3` and writer/cache identity distinguish this representation; phrase version remains `phase5-1`. Historical versions remain readable. MQTT envelopes and numerical/policy formulas are unchanged.

Failed optional generation updates the durable job/audit, without changing report revision, rendered content, PDF identity or review state. The reference GET report/briefing responses expose latest matching job metadata in top-level `generation`; deployed backend/UI must use that metadata for current generation status. A previously published `generation_pending` template is an immutable document snapshot, not a live job-status feed. Do not infer current job status from that old narrative field alone. Successful accepted refinement still creates a new revision and invalidates prior PDF/approval. Disabled writer emits one `model_disabled` template and creates no inference job. Reset/human edits cancel obsolete work while preserving history.

Adjacent native coverage intervals with identical state/source are coalesced only across a shared boundary. Freshness gaps remain separate and external receipt identity/conflict checks are unchanged. This bounds local ledger growth without changing coverage definitions or erasing historical external receipts.

The local model transport requests bounded SSE streaming so cancelling obsolete HTTP work is visible to the server during generation. No partial stream is published: a valid stop and `[DONE]`, complete compact schema, exact fact expansion and final current-run/revision/deadline check are all required before acceptance. Truncated, malformed, duplicate-key or forbidden reasoning/tool streams fail closed. This is transport isolation, not permission to stream unfinished prose to screens.

## Deployment responsibilities (unchanged)

Backend: real staff authentication/role binding, protected roster/profile, source coverage/suppression authority, public API/WS, record replacement and retired-run rejection. Antara: S8/S10, missing-field/checklist/provenance/urgent display and no auto-send. Kartik: actual A3 evidence availability/hashes. Broker/deployment owner: publisher ACLs and TLS; only backend can publish control/requests, only designated owners can publish records/actions, monitor accounts publish their vitals only. The local broker ACL test is not proof of deployed ACL configuration. LinuxONE owner: actual model/artifact byte order, resources and workflow latency. None is marked complete by a local stub.
