# Doc 00 v1.1 demo lifecycle integration

This implementation follows the locked **00 How our parts connect (read first) — v1.1**
contract. It wraps the unchanged production research scorer
`m6-research-0.3.4`. It does not import or merge the C1 readiness candidate.

## Enable the isolated demo runtime

Apply migration `0004_demo_lifecycle`, provide the 12-bed context template, and enable both
flags in a `test` or `demo` profile:

```text
SENTINEL_M6_ENABLED=true
SENTINEL_DEMO_LIFECYCLE_ENABLED=true
SENTINEL_M6_CONTEXTS_FILE=/etc/sentinelward/demo-m6-contexts.v1.1.json
```

The lifecycle state uses `automation.demo_m6_runtime`, separate from the non-demo
`automation.m6_states` namespace. One database transaction serializes control, source-end,
and physiological-frame handling. The demo control subscriber uses MQTT QoS 1.

## Locked MQTT contracts

The backend publishes `ward/demo/control`:

```json
{"v":1,"type":"demo_control","ts":1792252800000,"cmd":"run","run_id":"run_20261017_160000","start_at_s":0}
```

`cmd` is exactly `run` or `reset`. A run ID is single-use. The command timestamp must advance,
and the new episode timeline must start after every accepted frame in earlier cycles. An exact
redelivery is idempotent. A reset must name the active or most recent run. Invalid versions,
commands, identities, or ordering are dead-lettered and cannot mutate lifecycle state.

`run` creates a new per-bed episode identity, clears all demo M6 state and replay cursors, and
starts every configured bed at the requested script offset. It retains the last displayed values
until that bed's first frame arrives. `reset` clears every demo episode context, sequence cursor,
baseline, frozen baseline, pressure-review history, residual/Page–Hinkley state, peer evidence,
and predictor state. It does not delete ingress, audit, score, or outbox history. It does not
change model version or configuration.

Pending score deliveries from a closed run are retained with `unknown` status and are not retried.
Every demo score also carries `extra.demo_run_id`, `extra.episode_id`, and `extra.demo_only=true`.
The backend must reject an old run ID if an MQTT delivery was already in flight when reset occurred.
The locked vitals schema has no `run_id`; therefore ordinary old frames are rejected by the new
episode timestamp and device bounds, while broker ACL and the simulator connection remain part of
the trust boundary. Adding a frame-level run ID requires a future shared contract revision.

## Requests and records

`ward/request` includes `by` and is always parsed. `ack_alert` and `escalate_alert` route to A1
with that actor identity. `isolate_device` and `undo_action` are audited as requests owned by other
integration handlers; M6 never consumes a human action request.

`ward/record` accepts the locked ownership mapping:

| Kind | Owner |
| --- | --- |
| incident | A3 |
| report | A5 |
| ticket | A6 |
| workload | A7 |
| briefing | A8 |

`MqttRecordPublisher` sends typed agent records to `ward/record`. M6 outputs remain only on
`ward/bed/<bed_id>/score/M6`; lifecycle code never republishes them as records.

## Recording completion and OFFLINE

Known script completion is system/device lifecycle state:

| Bed | Source end | Recording duration in the script |
| --- | ---: | ---: |
| B03 | T+330 s | 330 s |
| B04 | T+420 s | 330 s after its T+90 join |
| B07 | T+870 s | 330 s after its T+540 join |

The lifecycle clock marks these beds offline at the declared time. The simulator or backend may
also call authenticated `POST /internal/v1/demo/source-end` with a typed, run-scoped
`demo_source_end` event. This is an internal callback, not an added MQTT topic. Completion preserves
`latest`, records `offline_since`, stops further frames for that episode, and never calls M6.
Silence therefore cannot create a drift or emergency score. A bed can resume only in a new valid
run/episode. `GET /internal/v1/demo/status` returns the screen-facing live/offline state, last values,
offline timestamp, episode identity, and cursor.

The lead-owned public backend still needs to project that authenticated internal state into its
locked `GET /api/ward`, `GET /api/bed/:bed_id`, and WebSocket payloads. The lead-owned simulator
must stop its iterator and send the completion callback when the source ends. The handler also
enforces the known end times as a deterministic backstop.

## Honest M6 baseline feasibility in the normal demo

The production requirement stays 900 seconds / 179 consecutive eligible windows.

| Beds | Can complete the full baseline in the normal script? | Measured contract reason |
| --- | --- | --- |
| B01, B02, B05, B06, B11, B12 | No | Doc 12 assigns ECG/PLETH sources; no ART/cuff input is declared. |
| B03, B04, B07 | No | Each available recording is 330 s, at most 65 aligned 10 s/5 s windows. |
| B08 | No | The scripted ART drift starts at T+300, before a clean 900 s baseline can finish. |
| B09 | No | The scripted pressure fall starts at T+360 and patient-review guards interrupt baseline collection. |
| B10 | No | The scripted drift starts at T+360, before a clean 900 s baseline can finish. |

B08–B10 have enough wall-clock duration in the 20-minute script, but their declared scenarios do
not contain 900 clean seconds before the fault. The normal v1.1 demo therefore does not honestly
exercise the full combined M6 path from a fresh run. Production M6 may show its cuff-gap-only path
on fresh cuff opportunities and labels it `assessment_path=cuff_gap_only`; missing or unassessed
evidence is never shown as stable.

A full combined-path demonstration must use a separate, explicitly labelled, long production-M6
replay with 900 eligible pre-fault seconds. No baseline is preloaded, no threshold is shortened,
and C1 is not used to make the normal demo pass.

## Teammate integration boundaries

- Lead/backend: publish control, call source-end, filter score run identity, and expose offline state
  through the public API/WebSocket.
- Lead/simulator: stop emitting frames at source completion and resume only after a new run.
- Kartik/A2: consume `isolate_device`; model scoring remains separate.
- A3/A5/A6/A7/A8 producers: publish their owned typed records; backend applies its locked
  same-`record_id` replacement behavior.
- Every other model/agent owner: handle `reset` for its own per-bed runtime state. This repository's
  implementation clears M6 only.

No clinical validation follows from these integration tests.
