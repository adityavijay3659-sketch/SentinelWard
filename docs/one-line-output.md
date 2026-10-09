# One-line output compatibility

## Purpose

SentinelWard integrations need two views of the same event:

1. Canonical JSON for validation, routing, storage, replay and audit.
2. One deterministic line that a person can identify quickly in a log, message or screen.

The JSON is always authoritative. The line is derived from it and must never be used as an input contract.

## Audience views

Every phase (0–7), including future A2–A8 integrations and verification, exposes
three views of the same validated event:

| Audience | Form | Intended use |
|---|---|---|
| Clinical user | short one-line instruction with an uppercase urgency label and no staff IDs | screen and phone comprehension |
| Team/operator | deterministic one-line status with canonical IDs and correlation facts | logs, debugging and handoff |
| Model/service | unchanged locked v1 JSON | validation, routing, replay and automation |

For internal alert command responses these are returned as `outputs.user`, `outputs.team` and
`outputs.model`. The existing `summary` remains an alias of `outputs.team` for compatibility.
Locked MQTT bodies are unchanged; consumers must not add an output field to `ward/alert` or
`ward/action`.

Example:

```text
USER  16:00:03 UTC | B02 | EMERGENCY ALERT | Bed 2 — possible heart emergency. Go now. | RESPOND NOW
TEAM  16:00:03 UTC | B02 | A1 EMERGENCY STEP 1 | al_0042; to=staff:priya; Bed 2 — possible heart emergency. Go now. | OPEN
MODEL {"v":1,"type":"alert","alert_id":"al_0042",...}
```

These lines are fixed-template projections of validated fields. Granite or any other generative
model must not compose, embellish or infer live emergency wording.

Display input must exclude patient names and secrets at the producer boundary.
The renderer removes control characters and bounds display length; it does not
claim to identify every possible personal name in free text. User action output
uses fixed action labels; operator details remain in team/model views.

An input request does not prove an outcome. Bedside messages say `CHECK REPORTED`;
the resulting alert state proves closure or continuation. Escalation says
`ESCALATED`; a separate delivery action proves phone delivery. M6 research scores
carry `RESEARCH` and their validation status. Potential deterioration carries an
`URGENT` patient-check label even when drift input is missing. A numeric M6 evidence
index of zero on such a window is not a normal-patient verdict.

M6 0.3.1 partial assessments explicitly show `M6 GAP-ONLY` in the team view.
A measured pressure gap below the drift threshold says `WARNING: PRESSURE GAP`
in the user view, rather than claiming its measured inputs are missing. Full
machine output distinguishes gap-only from combined baseline assessment and
retains the pending clinical-validation state. Patient-check urgency always
takes precedence. See [verified M6 examples](m6-revalidation-2026-10-09.md).

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
