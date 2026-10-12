# SentinelWard demo v1.1 integration contract matrix

This matrix records the contracts implemented in this repository and the exact boundary still expected from the backend, simulator, agents, and broker. It describes integration behavior only. Production M6 remains `m6-research-0.3.4`, and the C1 candidate is not part of this runtime.

## Boundary matrix

| Boundary | Producer | Consumer | Implemented schema and fields | Version | Ownership and status |
| --- | --- | --- | --- | --- | --- |
| `ward/demo/control` | Trusted backend/demo controller | Automation demo lifecycle | `DemoControlMessage`: required `v`, `type=demo_control`, `ts`, `cmd`, `run_id`; optional `start_at_s` defaults to 0. `cmd` is `run` or `reset`. | Integer `v=1` | Local parser and lifecycle **implemented**. Publishing and operator authorization are a backend/deployment dependency. |
| `ward/request` | Backend/UI acting for an authenticated person | Central request router; A1 for acknowledge/escalate | `RequestMessage`: required `v`, `type=request`, `request_id`, `ts`, `by`, `action`, `target_id`; optional `bed_id`, `note`. Actions: `ack_alert`, `escalate_alert`, `isolate_device`, `undo_action`. | Integer `v=1` | Parsing/routing **implemented**. A1 actions execute locally. A2 isolation and original-owner undo execution remain external. M6 never consumes this message. |
| `ward/record` | A3/A5/A6/A7/A8 through the record publisher | Backend record store/projection | `RecordMessage`: required `v`, `type=record`, `ts`, `kind`, `record_id`, `by`, `data`. Kinds/owners: incident/A3, report/A5, ticket/A6, workload/A7, briefing/A8. Incident data additionally requires an `evidence` list. | Integer `v=1` | Typed contract and MQTT publishing adapter **implemented**. Backend replacement of an existing `record_id` remains backend-owned. |
| `ward/bed/<bed_id>/score/M6` | Production M6 demo handler | Backend/decision layer | `ScoreMessage`: standard score fields plus demo metadata in `extra`: `demo_run_id`, `episode_id`, `demo_only=true`. Topic bed must match payload bed. | Score schema `v=1`; model version remains in the score | Local publishing, persistence, and outbox identity **implemented**. Backend stale-run rejection remains required. |
| M6 vitals input topic | Simulator/device gateway | M6 service | `VitalsMessage`: strict envelope with required `v`, `type`, `bed_id`, `device_id`, `ts`, `seq`, and nullable signal/readout fields defined in `contracts.py`. The locked frame schema has no `demo_run_id`. | Integer `v=1` | Local validation and episode/timestamp/sequence checks **implemented**. Simulator source binding and broker publisher trust remain external. |
| Internal `POST /internal/v1/demo/source-end` | Authenticated simulator or backend | Demo lifecycle | `DemoSourceEnd`: required `v`, `type=demo_source_end`, `run_id`, `ts`, `bed_id`, `device_id`, `source`, `reason=recording_complete`; source is `simulator` or `backend`. Bearer token is required. | Integer `v=1` | Endpoint and idempotent transition **implemented**. Calling it when a recording ends is a simulator/backend dependency. |
| Internal `GET /internal/v1/demo/status` | Authenticated internal client | Demo lifecycle | No message body. Returns run state and per-bed `state`, `offline_since`, `latest`, `latest_ts`, `recording_complete`, `episode_id`, and replay cursor. | Response `v=1` | **Implemented** internal projection. |
| Public `/api/ward`, bed API, WebSocket/update stream | Backend | UI and other consumers | Backend must project the current run and each bed's lifecycle state from the internal status. No public payload schema is implemented in this repository. | Contract not present locally | **Backend dependency**. Do not infer a public schema from the internal one. |

## Effects, errors, identity, and idempotency

| Boundary | Expected acknowledgement/effect | Malformed or unauthorized behavior | Idempotency and demo identity | Security assumption |
| --- | --- | --- | --- | --- |
| `ward/demo/control` | `run` creates fresh per-bed episodes and state; `reset` clears demo M6 runtime state while preserving audit/history. MQTT processing ACKs accepted or safely rejected ingress. | Strict parsing rejects unknown fields, versions, types, and commands. Invalid ordering/run identity is dead-lettered and cannot reset state. | Exact redelivery is idempotent. Run IDs are single-use. Each accepted run generates deterministic run-scoped bed episode IDs. | Broker ACL must identify and authorize the publisher because the payload has no actor field. |
| `ward/request` | A1 acknowledges or escalates the target alert. The request actor in `by` is retained; A1 action output uses it as `approved_by`. Other owned actions are audited for their integration handler. | Strict parsing rejects malformed/unknown actions. A1 roster/target checks reject invalid execution. No request enters M6. | Durable ingress deduplicates the same message/event identity. `request_id` is the correlation identity. | Backend must authenticate the human and publish an honest `by`; broker ACL restricts publishers. |
| `ward/record` | QoS 1 publish to backend. | Invalid owner/kind, version, schema, or non-finite JSON is rejected before publish. | Exact same body/record identity deduplicates locally. A changed body with the same `record_id` is deliverable; replacement semantics are backend-owned. | Only the declared agent publishers should publish their record kind. |
| M6 score | Backend may update current bed/model state only after current-run validation. | Missing/mismatched `extra.demo_run_id` or `episode_id` must be rejected before projection, alerts, decisions, WebSocket, or UI state. | Outbox delivery key includes episode, bed, window, and model version. Pending/failed deliveries from a closed run are retired; an already in-flight message remains distinguishable by metadata. | Only the M6 automation identity may publish this topic; consumers must still validate run identity. |
| Source completion | Marks the named bed offline, records `offline_since`, preserves last values, and emits no M6 score. | Bad token is unauthorized; bad schema is rejected; stale run/device/bed context conflicts without mutation. | Repeated valid completion is a no-op. Timer and explicit completion converge on one transition. | Bearer token plus network boundary; the authenticated caller is trusted to identify a real source end. |
| Public bed projection | Exposes lifecycle state to API/UI. | Backend must avoid treating missing frames as a model conclusion. | Projection must be scoped to its active `demo_run_id` and current bed episode. | Backend authentication/authorization is external. |

## Demo identity trace and rejection boundary

1. A valid `ward/demo/control` `run` supplies `run_id`.
2. The lifecycle creates a fresh episode for every bed as `demo:` plus a deterministic hash of the run and bed.
3. Accepted vitals are evaluated only inside that active bed context.
4. `DemoM6Handler` adds `extra.demo_run_id`, `extra.episode_id`, and `extra.demo_only=true` to every demo M6 score.
5. The score body is persisted unchanged in the score/outbox path and serialized unchanged by the MQTT worker.
6. At backend score ingress, before any current-state mutation, compare `extra.demo_run_id` with the backend's active run and `extra.episode_id` with the active bed episode. Reject on a missing or unequal value.

The demo handler has no identified path that drops this identity. The non-demo M6 handler does not add demo identity and must not be used as the demo ingestion path. The local contract test proves that an old message is recognizable; it does not validate unavailable backend code.

## Offline projection requirement

The implemented internal status contains all source fields needed for offline display. A public example based only on those fields is:

```json
{
  "run_id": "run_20261017_160000",
  "bed": {
    "bed_id": "B03",
    "state": "offline",
    "offline_since": 1792253130000,
    "latest": {"hr": 78.0, "spo2": 97.0, "bp": 84.0, "rr": 16.0},
    "latest_ts": 1792253129000,
    "recording_complete": true,
    "episode_id": "demo:example"
  }
}
```

The backend must expose equivalent meaning in the ward list, bed detail, and update stream: explicit offline status, last known values, and `offline_since`. It must retain those values after source completion and must not synthesize an M6 alert from silence.

## Minimum broker ACLs

No broker configuration is stored in this repository, so configuration is a deployment dependency.

| Principal | Publish | Subscribe |
| --- | --- | --- |
| Trusted backend/demo controller | `ward/demo/control`, `ward/request` | M6 scores, `ward/record`, other outputs it projects |
| Simulator/device gateway | Only assigned vitals input topics | Control/run synchronization only if the shared deployment requires it |
| M6 automation | `ward/bed/+/score/M6` | Its assigned vitals topics, required M3/M5 evidence topics, `ward/demo/control`, `ward/request` for centralized routing |
| A3/A5/A6/A7/A8 identities | Only their allowed `ward/record` kind through the shared topic | Only inputs required by that agent |
| Decision/backend consumer | Its owned outputs | `ward/bed/+/score/M6` and other model outputs |

Use authenticated, scoped credentials and TLS. Demo-control authorization is entirely at the broker/backend trust boundary because `DemoControlMessage` intentionally has no actor identity.

## Source-completion ordering

- Explicit completion before the timer: the explicit event sets offline state; the timer is a no-op.
- Timer only: the known end time sets offline state.
- Explicit completion after the timer: it validates the active context and is a no-op; the first `offline_since` remains.
- Duplicate explicit completion: no duplicate state transition or audit event.
- Completion from an old run after reset/new run: rejected by run identity; it cannot stop the current run.

The in-memory lock or PostgreSQL transaction/advisory serialization protects these transitions. Tests show no duplicate-offline or stale-run race. An authenticated active-run source can intentionally complete early; that is part of caller trust rather than a concurrency defect.
