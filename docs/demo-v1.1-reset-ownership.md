# SentinelWard demo v1.1 reset ownership

This table distinguishes code proven in this repository from reset work owned elsewhere. A demo reset must preserve historical audit and record data while removing live state that could contaminate the next run.

| Component | Current evidence/status | Required reset behavior | Classification |
| --- | --- | --- | --- |
| M1 | No M1 runtime state implementation found in this repository. | Owner must clear per-bed/window/episode state and reject stale inputs after a new run. | Other model owner dependency |
| M2 | No M2 runtime state implementation found in this repository. | Same model-state and stale-context reset requirement. | Other model owner dependency |
| M3 | M6 consumes M3 scores; the M3 producer is not implemented here. M6's cached peer evidence clears locally. | M3 owner must clear its own runtime state and emit new-run context. | Other model owner dependency |
| M4 | No M4 runtime state implementation found in this repository. | Clear its own per-demo runtime state. | Other model owner dependency |
| M5 | M6 consumes M5 scores; the M5 producer is not implemented here. M6's cached peer evidence clears locally. | M5 owner must clear its own runtime state and emit new-run context. | Other model owner dependency |
| M6 | `DemoM6Handler` replaces run-scoped bed state on reset/run. | Clear baseline/frozen baseline, pressure history, residual/Page-Hinkley, predictor state, peer evidence, alignment/sequence, replay cursor, and episode context. Preserve audit, scores, configuration, and model version. | **Cleared locally** |
| Decision layer | General engine evaluation is request-scoped locally; the deployed multi-model fusion/decision state is not present. | Clear run-scoped fusion, suppression, correlation, and current projection state; retain audit history. | Other model/agent owner dependency |
| A1 alert coordinator | Alert state, escalation timers, and action records exist locally, but no direct demo-reset hook is wired into the M6 lifecycle. | Retire/cancel live alerts and timers belonging to the closed demo, preserve alert/action audit, and reject stale-run actions. | A1 integration owner dependency |
| A2 containment | Implementation is owned externally by Kartik. | Safely undo/retire demo containment state according to A2 policy; do not infer an undo from M6 reset. | **Kartik dependency** |
| A3 incident/evidence | Typed record contract exists; the generating agent/runtime is external. | Clear draft/session/cursors for the old run while preserving immutable evidence and published records. | Other agent owner dependency |
| A4 fleet watch | Runtime not found locally. | Clear run-scoped fleet correlation/cache state. | Other agent owner dependency |
| A5 report | Typed record publisher is stateless; the report-producing agent state is external. | Clear unfinished old-run report state; preserve published records. | Other agent owner dependency |
| A6 ticket | Typed record publisher is stateless; ticket workflow is external. | Clear old-run draft/aggregation state; preserve submitted tickets. | Other agent owner dependency |
| A7 workload | Typed record publisher is stateless; workload aggregation is external. | Reset demo-period aggregation/current state. | Other agent owner dependency |
| A8 briefing | Typed record publisher is stateless; briefing generation is external. | Clear old-run briefing context/drafts; preserve published briefings. | Other agent owner dependency |
| Simulator | Not implemented in this repository. | Stop iterators, discard old queued frames, reset source cursors, bind to the new run/episodes, and call source completion. | **Simulator dependency** |
| Attack script | Not implemented in this repository. | Stop injections/timers, clear fault phase and queued events, then bind explicitly to the new run. | Simulator/attack owner dependency |
| Backend/demo state | Public backend is not implemented here. | Set the active run, clear current bed/model/agent projections, reject old-run outputs, retain historical rows, and expose the new episode identities. | **Backend dependency** |

## Locally proven M6 reset invariants

- `run` begins with a newly constructed M6 state and replay cursor.
- `reset` is deterministic and idempotent.
- A subsequent run cannot reuse the previous baseline or pressure history.
- Page-Hinkley, residual, predictor, peer evidence, alignment, and sequence state do not survive.
- Stale episode inputs do not populate the new episode.
- Pending/failed old-run score deliveries are retained for audit as `unknown` and are not retried.
- Model version, model configuration, thresholds, database audit history, scores, and records are not deleted or mutated.

This proves M6 lifecycle reset locally. It does not prove a system-wide reset until every external owner completes and tests its row above. In particular, the A1 alert lifecycle needs an explicit owner decision and integration hook so old-demo timers cannot act in a new run.
