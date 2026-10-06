# Agent registry, authority and completion rules

The registry is deny-by-default. An action not listed here is refused and logged.

| Agent | Owner | Trigger | Allowed actions | Human boundary | Completion evidence |
|---|---|---|---|---|---|
| A1 Alert | Aditya + Antra | nurse-facing verdict | `send_message`, `edit_message`, `escalate`, `record_ack` | nurse acknowledges and checks patient | ladder state and response time logged |
| A2 Containment | Kartik; hosted by Aditya | `TAMPERING`/`BOTH` above approved threshold | `disable_client`, `set_bed_untrusted`; `enable_client` only for undo | IT performs undo | isolation, untrusted state and undo audit |
| A3 Evidence | Kartik; hosted by Aditya | `TAMPERING`, `DEVICE_ATTACK`, `BOTH` | `snapshot_files`, `hash_file`, `write_timeline` | none | hashes re-check; timeline matches audit |
| A4 Fleet hunt | Kartik; hosted by Aditya | successful A2 containment | `list_devices`, `set_watch_level` | IT decides further isolation | same-model list and expiring watch level |
| A5 CERT-In | Aditya | IT confirms incident | `draft_report`, `start_clock` | person checks and sends externally | fields filled/flagged; no send capability |
| A6 Biomed | Aditya | any drift or 3 loose events/30 min/device | `open_ticket`, `update_ticket` | biomed closes ticket | repeats merged; correct device/bed/fix |
| A7 Workload | Aditya | every minute | `warn_workload` | charge nurse decides reassignment | two-hour counts and warning stored |
| A8 Briefing | Aditya + Antra | shift end or Generate now | `write_briefing` | staff reads/accepts | every numeric claim verified |
| A9 Learning | Aditya | future weekly process | no runtime actions in datathon | person approves proposals | design description only |

## Router matrix

| Verdict | A1 | A2 | A3 | A4 | A5 | A6 |
|---|---:|---:|---:|---:|---:|---:|
| `NORMAL` | no | no | no | no | no | no |
| `EMERGENCY` | yes | no | no | no | no | no |
| `BOTH` | yes | yes | after A2 | after A2 | after IT confirms | no |
| `TAMPERING` | yes | threshold-dependent | yes | after A2 | after IT confirms | no |
| `UNSURE` | yes | no | no | no | no | no |
| `DRIFTING` | yes | no | no | no | no | yes |
| `LOOSE_SENSOR` | yes | no | no | no | no | after repetition rule |
| `DEVICE_ATTACK` | IT alert only | policy-dependent, never nurse-facing | yes | after A2 | after IT confirms | no |

A7 and A8 are scheduled/explicit workflows and do not depend directly on one verdict.

## Approval rules

- A2 may perform the first approved containment action immediately; only IT can undo it.
- A4 may raise watch levels but cannot isolate another device.
- A5 cannot send a report because no send tool exists.
- A7 cannot reassign a bed or nurse.
- A8 cannot alter source facts.
- Any proposed treatment action is rejected before workflow routing.
- Granite output cannot become an action request.

## LangGraph state shared by every agent

- stable workflow/thread ID;
- correlation and idempotency keys;
- validated trigger snapshot;
- requested and authorized action;
- approval status and approving identity, when applicable;
- attempt count and last error;
- external result reference;
- action/undo identifiers;
- terminal status: `completed`, `rejected`, `failed` or `cancelled`.

