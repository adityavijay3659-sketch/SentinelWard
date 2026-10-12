# Phase 4 interfaces and isolated integration contract

Implemented from Doc 00 v1.1 and the user's revised Phase 4 decisions. The locked MQTT envelopes are unchanged. This file describes new internal interfaces and the local backend reference, not a deployed teammate API.

## Runtime profile

Phase 4 is disabled unless `SENTINEL_PHASE4_CONFIG_FILE` is provided. The supplied factory requires the `test` environment, loopback HTTP and MQTT, enabled demo lifecycle, unique inventory bindings and `lab_owned=true` for every device. Production M6/C1 are not modified. The demo M6 requirements stay 900 seconds/179 windows/0.6 drift threshold/120-second cuff age.

The isolated factory supplies actual local Mosquitto control, filesystem evidence and PostgreSQL-backed projection/watch state. The coordinator accepts replaceable `BrokerControl`, `ProjectionPort`, `WatchPort`, and `AgentRepository` implementations. Kartik can replace those adapters while retaining workflow contracts. Deployment requires a new trusted backend adapter; the local factory deliberately rejects remote/non-lab configurations.

## MQTT and internal HTTP boundaries

| Boundary | Required effect |
| --- | --- |
| `ward/demo/control` | Existing M6 handler validates first; agent coordinator applies idempotent run/reset. Partial transient work retains ingress for retry. |
| `ward/bed/+/verdict` | LangGraph executes A1 independently, then the journalled Phase 4 workflow. Non-A1 simulated-success fallback is bypassed when Phase 4 is enabled. |
| `ward/request` | A1 retains roster checks and retired-run rejection. Isolate/undo requires separately registered identity, IT role, action, target, current run and non-expired authorization. |
| `ward/action`, `ward/alert` | Phase 4 additionally subscribes to these for incident timelines. They are observations, never executable instructions. A3 writer events cannot recursively trigger the writer. |
| `ward/record` | A3 incident and A6 ticket records only; agent service does not subscribe to its record topic. Backend owns replacement/projection. |
| `GET /internal/v1/phase4/status` | Bearer-authenticated state, active run, tickets, incidents, effects, watch leases and offline projection. |
| `POST /internal/v1/phase4/authorizations` | Trusted backend registers `request_id, by, role, action, target_id, run_id, expires_ts`. Replacing an existing registration with different data is rejected. |
| `POST /internal/v1/phase4/tickets/<id>/status` | Trusted backend submits authorization plus `status, expected_revision, note`. Requires biomed role/current scope. Unknown/stale/unauthorized edits return 404/409/403. |

Authorization role is not added to `ward/request`; the trusted backend supplies it through the internal authenticated boundary. Possession of an actor name or a device-field instruction grants no authority.

## Isolated backend reference

`create_reference_backend` is test-only and supports `/api/ward`, `/api/tickets`, `/api/actions`, `/api/incidents/<id>`, ticket PATCH and `/internal/v1/reference/records`. Every successful response carries `reference_only=true`. It uses server-configured bearer-token-to-staff-role bindings for human PATCH; a service token does not act as a biomed token. In normal isolated `serve` mounting, human tokens must be explicitly supplied to the reference factory for public PATCH, or the trusted backend can use the internal status-command boundary.

RecordProjection requires a current run and a positive integer `data.revision`; it rejects old-run, equal and older revisions. This proves the required comparison locally. The actual backend must implement equivalent replacement, authorization and UI/WebSocket behavior. No WebSocket/screens deployment is claimed.

## Effects and recovery

The supported runtime has one automation worker/scheduler leader. The coordinator serializes operations and PostgreSQL transactions use an advisory lock. A pending effect is committed before an external operation; final state, canonical action and audit/outbox are committed together. On ambiguous response, status is `unknown`. Redelivery reconciles broker state before retrying. Incomplete agent workflows do not mark ingress processed. Completed business effects reuse their identities across repeated scoring windows.

Containment steps are independent: disable, cleanup, and untrusted projection. The operator can see partial success; no failed cleanup is called full containment. The maintenance identity connects using the device's configured client ID and a clean session, without enabling the disabled device identity or receiving application-topic permissions. Real-broker tests verify rejected reconnect and removal of the old persistent subscription and an unacknowledged QoS 1 delivery.

There is no deployment threshold default. Local lab tests supply an explicit fixture policy; `0.8` in generated test configuration is a containment fixture, not M6's threshold or an approved live policy. For an injected deployed coordinator, automatic containment requires an approved policy/version/comparator.

## Evidence and watch state

A3 freezes up to ten minutes of available accepted observations. Each artifact has path, size, source and SHA-256; missing context remains explicit. `incomplete_context_verified` means existing artifacts verified but some sources are missing. A failed re-hash becomes `incomplete_integrity`. The network artifact is an MQTT message transcript, not a PCAP. Timelines are immutable numbered JSONL revisions with their own hashes and canonical action/audit events.

A4 operates only after confirmed containment. Other devices of the same configured model receive separate one-hour leases; firmware is retained in inventory. Duplicate triggers do not extend the incident's lease. Leases expire independently and the effective watch set is replaced idempotently. This is local watch-state integration; actual M4/M5 watch consumption and any approved policy changes remain model-owner responsibilities.

## Tickets, undo and lifecycle

A6 opens/updates one unresolved ticket per device on DRIFTING or three loose-sensor episode starts in `(t-30 minutes,t]`. Only NORMAL ends the current fault occurrence; missing/unsure/offline does not establish recovery. Different faults merge with separate data. Status is new/in_progress/done. Normal does not close a ticket. Closure is human; later continued observations cannot reopen it, but a genuinely new episode can create another ticket.

Updates use a stable record ID and increasing revision. Thirty-day counters count distinct recorded occurrences in the same demo namespace; replay runs are not real equipment history. No missing gap/duration is invented.

Undo resolves the actual original owner. A2 enables/reconnects without declaring physiological trust restored. A4 removes only the watch changes introduced by that action. A6 restores an unchanged earlier revision or marks a newly opened ticket cancelled, explicitly stating that no repair is claimed. Later human/agent edits cannot be overwritten by ticket undo. Immutable evidence and read-only discovery are retained, not erased by a fictitious undo. PostgreSQL mirrors compensation receipts in the existing unique `automation.undo_links` table.

Reset retires old-run outbox/timers, clears active buffers/occurrences/watches and preserves history. A1 alerts have an internal demo identity that does not alter the locked alert wire payload. Unrelated alerts are not retired. New local runs may restore only harness-owned broker accounts; production accounts still require authorized IT undo. Known recording ends project OFFLINE, offline_since and last values without executing M6 from a timer.

Before team deployment, connect real backend authorization/projection, Kartik's adapters and PCAP capture, model watch consumers, simulator and Antara's screens; inspect actual ACLs. Local fixture/reference results must not be represented as live team or clinical validation.
