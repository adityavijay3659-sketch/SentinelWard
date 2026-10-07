# Team inputs, outputs and integration handoffs

## Working rule

Every integration starts against a fixture and an adapter. Switching from fixture to live teammate service must not change workflow logic.

## Output compatibility rule

- Teammate services exchange and persist the canonical JSON; they do not parse the human-readable line to recover data.
- The automation service derives the same one-line view for logs, Telegram previews, screens and handoff evidence using the fixed renderer in `contracts.md`.
- Producers send canonical IDs, timestamps, enums and correlation IDs. They do not create their own prose variants.
- Antra may display the derived line, while the backend retains the source JSON and correlation ID for drill-down and audit.
- Granite may write narrative briefings and report drafts, but never operational statuses, identifiers, verdicts or action results.
- Integration tests compare the JSON first and then check that its derived line is one physical line and no longer than 160 characters.

## Aditya Singh — platform and backend

Aditya needs:

- MQTT broker URL, TLS/authentication method and test credentials;
- PostgreSQL connection and schema ownership boundaries;
- staff roster and device-inventory fixtures;
- backend callback for alert acknowledgements and bedside checks;
- approval or replacement for `POST /internal/v1/agent-events`;
- health-check and startup-order expectations.

Aditya provides:

- canonical contract package and examples;
- `ward/action`, `ward/alert` and M6 score publishers;
- event payloads for tickets, reports, workload and briefings;
- readiness/health status for the backend to display.

Joint acceptance: one recorded verdict is persisted once, reaches the screen and remains recoverable after restarting the automation service.

## Aditya Singhal — AI models and decision layer

Aditya needs:

- one valid v1 fixture for every canonical verdict;
- the final containment threshold input and safety-rule behavior;
- exact five-second `window_start` alignment;
- M3 score availability for M6 cause evidence;
- review of M6 features, calibration and emergency protection.

Aditya provides:

- a valid M6 v1 score every five seconds when data is sufficient;
- documented `null`/insufficient-data behavior;
- validation results for drift delay and genuine hypotension.

Joint acceptance: `BOTH` concurrently triggers A1 and eligible A2 handling, and genuine emergency evidence is never downgraded by M6.

## Kartik — cybersecurity and A2–A4

Aditya needs:

- A2, A3 and A4 handlers behind agreed typed adapter interfaces;
- disable/enable-client result format and error cases;
- network-capture/evidence locations;
- same-model inventory fields and watch-level expiry behavior;
- slow malicious drift and prompt-injection fixtures.

Aditya provides:

- LangGraph hosting, checkpointing and retry boundaries;
- policy enforcement and IT-role approval checks;
- action logging, idempotency and undo coordination;
- aligned M6 result for slow-drift scenarios.

Joint acceptance: repeated delivery cannot isolate twice; undo restores the client once; evidence hashes re-check; an injected instruction in a device field changes no action.

## Antra — screens and messaging

Aditya needs:

- final Telegram templates, button labels and callback payload convention;
- role visibility for nurse, doctor, IT and biomed views;
- UI expectations for pending, failed, acknowledged, untrusted and undone states;
- presentation format for tickets, reports, workload and briefings.

Aditya provides:

- stable alert identity and ladder state;
- acknowledgement and escalation events;
- typed screen-facing artifacts with correlation IDs;
- deterministic one-line summaries derived from those typed artifacts;
- Granite text plus a flag showing Granite or template provenance.

Joint acceptance: acknowledgement from screen or Telegram stops the same ladder, updates the same alert and never creates a duplicate event.

## Integration checkpoints

| Time | Integration target | Owners |
|---|---|---|
| Hour 2 | contracts, broker and persistence smoke test | Aditya + Aditya Singh |
| Hour 6 | one verdict to phone alert, ack and screen | Aditya + Antra + Singh + Singhal |
| Hour 10 | first M6 score and reviewed real-drop case | Aditya + Singhal + Singh |
| Hour 12 | containment/evidence/undo and biomed ticket | Aditya + Kartik + Antra |
| Hour 16 | all critical features frozen | whole team |
| Hour 19 | golden scenarios and final measurements complete | whole team |

Between checkpoints, teammates work against fixtures. Contract changes are batched for a checkpoint instead of interrupting everyone continuously.
