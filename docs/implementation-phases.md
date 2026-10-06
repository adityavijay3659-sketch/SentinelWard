# Implementation phases after Phase 0

This is the execution order for 17–18 October 2026. Phase boundaries are acceptance gates, not merely elapsed-time targets. If a gate fails, preserve the last working checkpoint and reduce optional scope instead of weakening a safety rule.

## Phase 1 — Foundation, hours 0–2

Build:

- typed contracts and live-wire validation;
- MQTT ingress and outbound adapters;
- verdict idempotency and dead-letter handling;
- LangGraph router and per-agent subgraph registry;
- policy guard, checkpoint persistence, action audit and undo registry;
- fake adapters for Telegram, backend events and Mosquitto control.

Gate: a fixture verdict creates one allowed action, rejects an unauthorized action and recovers after restart without duplication.

## Phase 2 — A1 alert ladder, hours 2–6

Build:

- verdict-to-message routing;
- assigned nurse, next nurse, all nurses plus doctor ladder;
- restart-safe 30-second demo timers;
- acknowledgement, message editing and timer cancellation;
- `BOTH` fan-out and bedside-check input;
- screen alert fallback when Telegram delivery fails.

Gate: one live bed reaches a phone and screen; acknowledgement edits the existing alert, stops escalation and records response time.

## Phase 3 — M6, hours 6–10

Build:

- VitalDB ART/NIBP loader and common window alignment;
- cuff-gap, patient baseline, Page-Hinkley and waveform-shape features;
- validation calibration and v1 M6 score publication;
- input-sufficiency and emergency-compatible safeguards;
- slow sensor versus malicious drift test harness.

Gate: M6 publishes aligned scores, detects injected drift with measured delay and makes zero drift calls on the held-out genuine-hypotension safety set.

## Phase 4 — A2–A4 integration and A6, hours 10–12

Build:

- typed adapters around Kartik's A2, A3 and A4 handlers;
- containment idempotency, action audit and IT-only undo;
- evidence completion state and hash verification;
- fleet-watch expiry;
- A6 drift/repeated-loose-sensor ticket rules and repeat merging.

Gate: a tampering scenario alerts, isolates, marks the bed untrusted, stores evidence and supports exactly-once undo; a drift opens one biomed ticket.

## Phase 5 — A5, A7, A8 and Granite, hours 12–16

Build:

- A5 report-field population, missing-field markers and six-hour deadline;
- A7 two-hour rolling alarm count and charge-nurse warning;
- A8 fact collection and shift/on-demand trigger;
- local Granite writer, numeric verifier and template fallback;
- screen-facing internal events for all artifacts.

Gate: every report field is filled or flagged, no send path exists, A7 cannot reassign staff, and every A8 number matches source data. Feature freeze follows this gate.

## Phase 6 — Verification, hours 16–19

Run:

- all eight verdict fixtures;
- duplicate, out-of-order and malformed messages;
- database, MQTT, Telegram, Granite and broker-control failures;
- restart during approval and escalation;
- `BOTH`, containment, evidence and undo;
- prompt injection and unauthorized-role attempts;
- final M6 safety and latency evaluation;
- 8–12-bed golden demonstration.

Gate: all critical tests pass and real measurements are recorded. Failed optional features are disabled cleanly rather than repaired after feature freeze.

## Phase 7 — Handoff and submission support, hours 19–22

Deliver:

- pinned environment and startup order;
- contract and fixture pack;
- agent permission matrix;
- health-check and troubleshooting guide;
- test-results summary and known limitations;
- demo reset/run instructions;
- screen and video evidence requested by Aditya Singh and Antra.

Gate: a teammate can start the service from the documentation and run the golden scenario without verbal instructions.

## Scope protection

If time becomes constrained, keep in this order:

1. engine safety, A1 and audit;
2. `BOTH` plus A2/A3 integration;
3. M6 real-drop safety;
4. A6 and deterministic report/briefing templates;
5. Granite wording;
6. A7 chart polish;
7. optional n8n visualization;
8. A9 remains design-only.

Never trade away emergency precedence, patient visibility, audit, human report sending or treatment isolation to recover time.
