# Canonical contracts and naming

## Contract authority

- **LOCKED:** Team `Doc 00 v1` MQTT topics, JSON fields and public backend addresses.
- **NORMALIZED:** This document resolves wording inconsistencies without renaming locked wire values.
- **PROPOSED:** The internal agent-event ingestion endpoint must be approved by Aditya Singh before implementation.

## Canonical verdict enum

Only these values are valid on `ward/bed/<bed_id>/verdict`:

| Canonical wire value | Meaning | Prose aliases that must not appear on the live wire |
|---|---|---|
| `NORMAL` | trusted, no action | normal |
| `EMERGENCY` | possible real clinical emergency | REAL EMERGENCY, real alarm |
| `BOTH` | emergency possible and tampering suspected | emergency plus attack |
| `TAMPERING` | body/network evidence suggests altered data | hacked, UNTRUSTED |
| `UNSURE` | insufficient/conflicting evidence | inconclusive |
| `DRIFTING` | likely gradual sensor drift | sensor drift |
| `LOOSE_SENSOR` | loose/noisy/unusable sensor | sensor fault |
| `DEVICE_ATTACK` | network attack without a nurse-facing clinical alarm | DEVICE UNDER ATTACK |

`UNTRUSTED` is a bed display/data-trust state set after containment. It is not a verdict.

## Fixed priorities

| Verdict | Priority | Required recipient/action |
|---|---|---|
| `NORMAL` | none | none |
| `EMERGENCY` | high | nurse ladder |
| `BOTH` | high | nurse ladder and A2 containment |
| `TAMPERING` | medium | bedside hand-check and IT |
| `UNSURE` | medium | bedside hand-check |
| `DRIFTING` | medium | bedside nurse and biomed ticket |
| `LOOSE_SENSOR` | low | refit sensor; eligible for ticket on repetition |
| `DEVICE_ATTACK` | none for nurses | IT only |

## Shared field rules

- `v` is integer `1` for every locked message.
- `ts` and `window_start` are Unix epoch milliseconds in UTC.
- IDs: beds `B01`–`B12`, devices `MON-01`–`MON-12`, models `M1`–`M6`, agents `A1`–`A9`, people `staff:<name>`.
- Missing physiological values are `null`, never `0`.
- Model scores are within `0.0`–`1.0`.
- A score `reason` is plain language and at most 120 characters.
- A verdict contains at most three reasons.
- MQTT QoS is 0 for vitals and 1 for all other messages.
- Verdict messages are retained; action and alert events are not retained.

## Topics consumed by Aditya's service

| Topic | Producer | Consumer behavior |
|---|---|---|
| `ward/bed/<bed_id>/verdict` | Aditya Singhal | validate, deduplicate and route |
| `ward/bed/<bed_id>/bedside` | backend/Antra | stop/update relevant workflow and audit |
| `ward/bed/<bed_id>/vitals` | Aditya Singh | M6 input only |
| `ward/bed/<bed_id>/score/M3` | Aditya Singhal | optional aligned M6 cause evidence |
| `ward/bed/<bed_id>/score/M5` | Kartik | optional aligned M6 cause evidence |

## Topics produced by Aditya's service

| Topic | Message type | Rule |
|---|---|---|
| `ward/action` | `action` | every attempted material action has one audit record |
| `ward/alert` | `alert` | publish on every A1 ladder-state change |
| `ward/bed/<bed_id>/score/M6` | `score` | one aligned score every five seconds when inputs permit |

## Idempotency and correlation

- Ingress verdict key: `bed_id:window_start:verdict`.
- Alert identity remains stable while the ladder advances; updates do not create a new alert.
- External action key: `correlation_id:agent_id:action:target_id`.
- A retry must return the stored prior result.
- An undo is a new `ward/action` record whose `undoes` references the original `action_id`.
- A failed attempt is also logged, with `result="failed"`; failures are never hidden by retry.

## Proposed internal backend event envelope

This does not replace a locked MQTT message. It carries screen-facing artifacts that have no locked write topic.

`POST /internal/v1/agent-events`

```json
{
  "v": 1,
  "event_id": "evt_000231",
  "event_type": "ticket.updated",
  "ts": 1792252801200,
  "source_agent": "A6",
  "bed_id": "B05",
  "device_id": "MON-05",
  "correlation_id": "B05:1792252795000:DRIFTING",
  "payload": {}
}
```

Allowed `event_type` families are `ticket.*`, `report.*`, `workload.*`, `briefing.*` and `workflow.*`. The backend authenticates the service identity, validates the payload subtype and persists it for the existing public read APIs.

## Contract change procedure

1. Open a written change proposal with motivation and compatibility effect.
2. Obtain Aditya Singh's approval.
3. Add rather than rename/remove whenever possible.
4. Bump the affected contract version if a locked interface changes.
5. Update fixtures and contract tests before implementation.
6. Notify all producers and consumers with an agreed switchover checkpoint.

