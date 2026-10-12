# SentinelWard demo v1.1 team smoke test

Run this checklist after the real backend, simulator, broker, UI, and component reset handlers are connected. Use a new unique run ID and retain all listed evidence. This is an integration test, not clinical validation.

## Preconditions

- Apply database migrations through `0004_demo_lifecycle`.
- Enable M6 and demo lifecycle only in the approved demo/test profile.
- Configure the 12-bed M6 context file and the authenticated internal lifecycle token.
- Configure scoped broker credentials/ACLs and start the outbox worker.
- Confirm backend stale-score filtering and public offline projection are deployed.
- Confirm each model/agent owner has declared its reset behavior from `demo-v1.1-reset-ownership.md`.

Use identifiers such as `run_A_<timestamp>` and `run_B_<timestamp>`. Never reuse a run ID.

## Deterministic sequence

| Step | Action | Expected result | Evidence to retain |
| ---: | --- | --- | --- |
| 1 | Publish a valid `reset` to `ward/demo/control` for the active/most recent run, or establish the documented initial empty state. | Lifecycle is inactive; M6 demo bed contexts and cursors are empty. Repeating reset is harmless. | MQTT command/ACK; internal status; `demo.control.reset` audit/log; DB rows showing history retained. |
| 2 | Publish `run` for run A with a fresh ID. | One active run and fresh episode IDs for all configured beds; model/config versions unchanged. | MQTT control payload; `GET /internal/v1/demo/status`; DB runtime/audit row; backend active-run log. |
| 3 | Start the simulator bound to run A and send valid vitals. | Frames advance only the matching bed episode and cursor. | Captured vitals MQTT frames; simulator run-binding log; internal status `latest`, `latest_ts`, cursor. |
| 4 | Wait for an M6 scoring window. | Score is contract-valid and contains `extra.demo_run_id=run_A`, current `extra.episode_id`, and `extra.demo_only=true`. A partial or insufficient assessment is valid; the normal short demo is not expected to complete the 900-second combined baseline. | M6 score MQTT payload; persisted score/outbox body; model log. |
| 5 | Inspect public live state. | `/api/ward`, bed detail, and WebSocket/update stream identify the current bed as live and show current readings. | API JSON, WebSocket message, and UI capture tied to run A. |
| 6 | Publish `ward/request` `ack_alert` as an authenticated actor against a real demo alert. Then exercise `escalate_alert` where applicable. | A1 executes centrally. Resulting action retains `approved_by` equal to request `by`; M6 receives no request. | Request MQTT payload; A1 action/audit DB row; action MQTT; UI acknowledgment; Telegram evidence only if escalation policy calls it. |
| 7 | Let one known short source finish (B03 at about T+330 s is preferred) and have the simulator call `POST /internal/v1/demo/source-end`. | Simulator stops frames for that episode. Bed becomes offline once. | Simulator completion log; authenticated HTTP result; one offline audit transition. |
| 8 | Inspect offline projection. | Internal and public views show `state=offline`, `offline_since`, and retained last known values. UI shows OFFLINE. | Internal status, `/api/ward`, bed API, WebSocket update, UI capture. |
| 9 | Wait beyond at least two normal scoring intervals without new frames. | No M6 score, drift, emergency, or alert is created solely from silence. | MQTT capture; score/outbox query; alert query; logs covering the quiet interval. |
| 10 | Hold one run-A score delivery, then publish valid reset/run B and deliver that old score to backend ingress. | Backend rejects the score before current bed/decision/alert/UI mutation because its run or episode differs. | Rejection log/metric with reason; unchanged run-B API/WebSocket state; old payload. |
| 11 | Complete reset for run A and verify every owner. | M6 state clears locally; other model/agent, decision, simulator, attack, A1, A2, and backend state clears according to the ownership table; audit/history remains. | Per-owner reset ACK/log; DB audit/history; absence of current old-run projections and timers. |
| 12 | Publish `run` for run B and restart simulator. | Fresh episode IDs and cursors; no previous baseline, pressure history, peer evidence, alerts, actions, or projected values appear as current state. | Run-B control, internal status, first frames/scores, backend APIs/WebSocket, owner reset logs. |

## Message examples

Control messages use the exact locked schema:

```json
{"v":1,"type":"demo_control","ts":1792252800000,"cmd":"run","run_id":"run_A_20261017_160000","start_at_s":0}
```

Source completion uses the internal authenticated endpoint rather than a new MQTT topic:

```json
{"v":1,"type":"demo_source_end","run_id":"run_A_20261017_160000","ts":1792253130000,"bed_id":"B03","device_id":"MON-03","source":"simulator","reason":"recording_complete"}
```

An accepted demo M6 score must include:

```json
{"extra":{"demo_run_id":"run_A_20261017_160000","episode_id":"demo:<run-scoped-id>","demo_only":true}}
```

## Database and log checks

Use the deployed schema names and read-only queries approved by the backend owner. Verify these facts rather than depending on a particular SQL query:

- The demo runtime singleton names the active run and current per-bed episode/cursor.
- Audit events exist for accepted control and offline transitions, correlated to the demo run.
- M6 score and outbox JSON retain `demo_run_id` and `episode_id` unchanged.
- Old pending/failed deliveries are `unknown` after reset and are not retried.
- Historical ingress, audit, score, alert/action, and record rows remain after reset.
- No score or alert timestamp appears after source completion unless a valid new episode supplies frames.

## Pass criteria

The smoke test passes only when the team can show all evidence above, including backend rejection of a delayed old-run score and reset acknowledgements from every stateful owner. A passing local M6 test does not substitute for backend, simulator, broker, UI, A1/A2, or other model/agent evidence.
