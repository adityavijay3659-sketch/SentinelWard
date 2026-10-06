# M6 drift watcher design

Owner: Aditya. Reviewer: Aditya Singhal. Platform/data support: Aditya Singh. Adversarial test input: Kartik.

## Question

Is the arterial blood-pressure sensor slowly becoming inaccurate while its values still look believable?

M6 estimates sensor drift. It does not issue a final clinical verdict and it does not take an action.

## Data

Use VitalDB cases that contain both:

- arterial waveform and values: `SNUADC/ART`, `Solar8000/ART_SBP`, `ART_MBP`, `ART_DBP`;
- cuff values: `Solar8000/NIBP_SBP`, `NIBP_MBP`, `NIBP_DBP`.

Training/validation examples include:

- genuine stable and changing blood pressure;
- known level offsets based on approximately 0.74 mmHg per centimetre;
- slow zero-drift ramps over 5–30 minutes;
- damping introduced by controlled smoothing;
- Kartik's slow malicious drift with aligned network evidence.

All patient splits are patient-wise. Thresholds and calibration are selected on validation data; the held-out test set is used once for final reporting.

## Processing

1. Align all inputs to the common 125 Hz stream and 10-second/five-second window convention.
2. Reject or mark insufficient windows with missing timestamps, implausible sampling or unusable ART.
3. Derive arterial MAP and waveform-shape features.
4. At each cuff reading, calculate ART MAP minus NIBP MAP; an absolute gap of 10 mmHg is the initial clinical rule signal.
5. During the first valid 15 minutes, fit a robust per-patient baseline relating expected MAP to heart rate, pulse-arrival time and pulse amplitude.
6. Track measured ART MAP minus predicted MAP and run Page-Hinkley for a persistent mean shift.
7. Measure shape changes that distinguish a level shift from damping.
8. Calibrate the gap, Page-Hinkley and shape evidence into an M6 score using validation data.
9. If an aligned M3/M5 window is present, add `cause_hint = sensor`, `tampering` or `uncertain`; absence of these inputs cannot fabricate certainty.

## Safety precedence

- If the cuff confirms the pressure fall, M6 must not call it ordinary sensor drift.
- If heart rate, pulse timing/amplitude and cuff pressure support the fall, mark the evidence as emergency-compatible for the decision layer.
- Network anomalies may change the cause hint but may not suppress emergency-compatible evidence.
- Missing cuff data reduces confidence; it does not become a normal result.
- The decision layer applies the final safety rule and verdict.

## Output

Publish the locked v1 score message with:

- `model = "M6"`;
- calibrated score from 0 to 1;
- label such as `drift`, `stable` or `insufficient_data`;
- reason no longer than 120 characters;
- `extra` containing available evidence such as `gap_mmhg`, Page-Hinkley statistic, shape indicator, cause hint and input sufficiency.

## Evaluation

- detection delay by drift size and drift speed;
- sensitivity by drift type: level, ramp and damping;
- false drift calls on genuine hypotension: required target is zero on the held-out safety set;
- sensor drift versus slow malicious drift confusion matrix;
- missing-cuff and bad-signal behavior;
- five-second inference latency and message alignment;
- failure examples reported alongside successes.

The final threshold is not hard-coded during Phase 0. The 10 mmHg cuff rule is fixed as an input signal; the combined score threshold is chosen on validation data and handed to Aditya Singhal for final decision-layer calibration.

