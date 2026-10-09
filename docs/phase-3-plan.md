# Phase 3 — M6 sensor-drift research implementation

Scope checked against locked Drive Doc 00 v1, Aditya automation v3 and R10 on
2026-10-09. M6 supplies evidence to Singhal's decision layer; it never diagnoses,
acknowledges alerts, suppresses an emergency, or operates a device. Telegram remains
a secondary channel. Existing v1 topics and shapes remain unchanged.

## Implementation sequence and acceptance

1. Validate v1 one-second vitals; align causal 10-second windows every 5 seconds.
   Reject nonfinite samples, future cuff readings and mismatched routing.
2. Extract cuff gap, pressure/pulse morphology and ECG-to-PPG timing proxy. Fit a
   robust within-episode baseline after 15 minutes of usable observations; track
   two-sided Page–Hinkley residual change. Missing inputs are not normal readings.
3. Preserve possible genuine pressure drops as emergency-compatible evidence.
   Fuse only time-aligned M3/M5 evidence; absent evidence means uncertain cause.
4. Persist bounded episode state and enqueue v1 M6 scores atomically. Replays and
   process restarts must not duplicate output. Publish QoS 1, non-retained.
5. Provide local VitalDB track CSV replay, patient-separated calibration and frozen
   evaluation tools. Measure injected drift and known hypotension separately.
6. Run regression/static/database/package checks; provide truthful examples and
   handoff contracts. Do not push without Aditya's instruction.

## Scientific gates, not assumptions

Hypothesis: cuff disagreement plus residual change can identify injected pressure
offsets without relabelling independently adjudicated hypotension as sensor drift.
Baseline comparator: absolute ART–fresh-cuff MAP difference >= 10 mmHg.
Observation: one aligned window; grouping/splitting unit: patient, not window.
Primary safety gate: zero false drift labels on the held-out, reviewed genuine
hypotension set. Report numerator, denominator and uncertainty; zero observations
is not a pass. Secondary metrics: drift sensitivity, false-positive rate, injected
drift detection delay, missing-input coverage and latency. No accuracy target is
invented on behalf of the team.

Synthetic tests verify software behavior only. A validation-derived threshold is
not a calibrated probability and not clinical approval. Real VitalDB processing,
adjudicated labels, held-out evaluation and Singhal's review remain required.

## Teammate boundaries

- Lead/backend: episode identifiers and start timestamps, device mapping, clock
  alignment, missing-frame semantics, authenticated broker/ACL and screen wiring.
- Singhal: score labels/extra metadata, M3/M5 semantics, safety-set adjudication,
  patient splits, calibrated threshold review and decision-layer integration.
- Kartik: independent offset/ramp/damping/tampering cases and fault injection.
- Aditya: deterministic pipeline, persistence, replay/evaluation, evidence report.

No patient identity is added to the v1 wire. Episode context is supplied out of
band; a new patient requires a new episode ID before their first frame. Device
changes and sequence resets require reviewed context updates, never blind reuse
of the preceding patient's baseline. Deployment is research-only until these
contracts and the safety gate are signed off.

## Output rule for every phase (0–7)

Human and team projections are deterministic, one physical line, at most 160
characters. Preserve urgency, subject and outcome; truncate explanatory text.
Use EMERGENCY, WARNING or RESEARCH labels where supported. Report requested,
queued, delivered, acknowledged and failed as different states. Never infer
delivery, recovery or closure from an input request. Machine JSON stays complete,
typed and versioned; it is not truncated to fit a display. Unknown, insufficient
and unvalidated results remain explicit. No LLM is involved in these projections.
