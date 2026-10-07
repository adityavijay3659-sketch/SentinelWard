# One-line output compatibility

## Purpose

SentinelWard integrations need two views of the same event:

1. Canonical JSON for validation, routing, storage, replay and audit.
2. One deterministic line that a person can identify quickly in a log, message or screen.

The JSON is always authoritative. The line is derived from it and must never be used as an input contract.

## Required form

```text
HH:MM:SS UTC | SUBJECT | SOURCE EVENT | KEY FACT | RESULT_OR_NEXT
```

Every renderer must produce exactly one physical line of at most 160 characters. It must sanitize tabs, carriage returns and line feeds, collapse whitespace and exclude patient names and other PHI. If shortening is required, shorten the key fact first while retaining the subject, source event and result.

## Automation coverage

| Producer/workflow | Compatible one-line responsibility |
|---|---|
| A1 alert ladder | emergency type, ladder level, recipient/ack fact and current state |
| A2 containment | action, device target, reason and result/undo availability |
| A3 evidence | evidence count or bundle ID and completion state; never secrets or raw paths |
| A4 fleet hunt | scope, watch duration and review state |
| A5 CERT-In | draft completeness/deadline and mandatory human-send state |
| A6 biomed | affected device/bed, issue and ticket state |
| A7 workload | staff or ward scope, alert count/window and review state |
| A8 briefing | shift scope, aggregate facts and readiness state |
| Granite writer | provenance and generation result only; generated prose remains separate |
| M6 drift model | canonical state/score, short reason and safe next step |
| Verdict router | verdict/confidence, reasons and routed agents/action |
| Bedside callback | result, staff ID and workflow update state |
| Delivery/retry | event ID, attempt fact and delivery state |

## Integration boundary

- Model owners publish valid canonical score or verdict JSON.
- Aditya's automation layer validates and correlates that JSON, performs policy-approved routing and renders the one-line view.
- The backend stores the JSON and correlation ID. It may also store the line as a disposable display projection.
- Antra's clients display the supplied line or reproduce it with the same fixed template; they do not ask an LLM to summarize live status.
- Kartik's handlers return typed results. The automation layer maps those results to canonical action JSON before rendering.

This keeps display wording consistent without coupling teammates to a prose parser. The examples in `fixtures/one-line-output-examples.json` are the Phase 0 compatibility fixtures.
