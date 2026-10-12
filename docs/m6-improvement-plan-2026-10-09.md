# M6 dataset, coverage and accuracy-improvement plan — 9 October 2026

Implementation update, 11 October: the [repair report](m6-repairs-2026-10-10.md)
records the completed versioned software repairs, environment verification and
coverage audit. The 9 October measurements below are historical comparisons.
The bounded new-patient pilot, feature/model experiments, reviewed clinical
evidence and live integration checks remain pending; no accuracy gain is claimed.
The [11 October source refresh](m6-source-refresh-2026-10-11.md) adds the updated
Drive/website requirement for causal patient-specific gap assessment and the
source-version/arterial-line metadata checks needed before the next pilot.

Status: **research proposal**, grounded in the
[resumption audit](resumption-verification-2026-10-09.md). No new download,
training, threshold change, runtime replacement or clinical collection occurred.
Scope is Aditya's M6. M1–M5 remain their owners' work. Existing research results
and failures remain immutable evidence.

The next useful step is an acquisition/reference and baseline-feasibility audit,
followed by a bounded longitudinal-data pilot. Choosing a more complex model
before resolving 2.40% assessment coverage will leave most windows unassessed.
Data availability, replay assumptions and component eligibility are separate
problems; better regression MAE alone does not establish a better drift watcher.

## 1. Define success without an ambiguous accuracy percentage

| Goal | Required measurements | Current evidence | Acceptance decision |
|---|---|---|---|
| Pressure prediction | Patient-macro and window MAE/RMSE/bias in mmHg; median/p95 error; within 5/10/15 mmHg; low-pressure and device slices | 8.5539 mmHg MAE against observed monitor MAP; only four test patients | Predeclare research improvement margin and tolerated slice regressions; independent-reference criteria need clinical review |
| Drift events | Sensitivity by fault type/size; precision; false alarm episodes per monitored bed-hour; PR curve | Controlled perturbation responses only | Define episode grouping, minimum fault magnitude/duration and false-alarm budget on reviewed validation data |
| Deterioration protection | False drift during genuine hypotension, missed/delayed urgent review; patient-level numerator/denominator and uncertainty | No reviewed genuine safety set | Existing zero-false-drift safety gate stays pending until qualified review and adequate observations |
| Coverage | All received/aligned windows, silence duration, each component's assessable fraction, abstention reasons and baseline-ready patients | 414/17,268 sufficient, 0/12 full baseline | Predeclare intended input conditions and minimum useful coverage; never exclude hard cases to pass |
| Response delay | Onset-to-first additional signal and sustained event; median/p95; missed or unassessable events retained | +15 offset delays 15–1,305 seconds | Clinical usefulness limit requires workflow review; separate compute, outbox, screen and phone latency |

Treat 98–99% event sensitivity as an aspiration to test jointly with coverage,
precision, false alarms and delay, not a promised result. A <1% error claim must
specify its denominator and unit. At 80 mmHg, 1% relative pressure error is
0.8 mmHg; this is entirely different from 1% classification error. Neither
`100 - MAPE` nor a 0.75 evidence index is classification accuracy.

For scale, zero errors in 299 independent patient-level Bernoulli observations
gives a one-sided 95% upper error bound just below 1%:
`1 - 0.05 ** (1/299)`. This calculation assumes independent comparable units;
299 overlapping windows do not qualify. It is an illustration of evidence size,
not an agreed clinical sample-size protocol or proof of readiness.

## 2. Audit the current streams before obtaining more data

Deliver a new, versioned quality report using the existing development recordings.
Keep raw inputs and existing artifacts unchanged. Report both exclusive routing
reasons and independent, overlapping availability masks for every window.

| Audit | Concrete work and completion evidence |
|---|---|
| Waveforms | Check native clock/rate, compact CSV interpretation, duplicates/conflicts, per-bin dropout and simultaneous ART/ECG/PPG duration. Compare selected segments with an official VitalDB reader. Quantify loss caused by the current all-125-bins/ten-complete-frames requirement. |
| Cuff provenance | Count distinct changed tuples separately from five-second exposed windows. Audit the three-track timestamp match (currently within 1 ms), one-second lookup tolerance, identical repeated tuples and held numerics. Distinguish confirmed acquisition, observed update and unknown acquisition. |
| HR and timing | Audit why all ten HR frames and at least three timing matches are required. Compare the current peak/upstroke proxy with causal, quality-scored beat pairing; measure matching failures and timestamp sensitivity. |
| Baseline | Report elapsed span, uninterrupted stretches, distinct reference observations, overlapping-window count and quality/pressure exclusions. Current 179 windows can span 85.5-minute gaps; do not interpret them as independent reference measurements. |
| Safety precedence | Retain low-pressure, fall and high-alarm guards. Report secondary missing evidence even when urgent review takes priority. Guard-trigger counts are not clinician-confirmed disease labels. |
| Missing data | Separate source absence, extraction failure, clock mismatch, deliberate safety routing and baseline ineligibility. Include complete input silence through the existing backend freshness boundary. |

Current replay recognizes a changed NIBP tuple as a conservative proxy. More
frequent held numeric samples are not fresh cuff acquisitions. Do not invent
events or substitute arterial MAP for a missing independent cuff. If raw files
also lack acquisition provenance, mark it unresolved rather than claiming the
parser can recover information that was never recorded.

An ideal cuff every five minutes with a two-minute freshness allowance exposes
at most roughly 40% of time to a fresh reference, even before waveform and safety
gates. This is a cadence illustration, not measured VitalDB cadence. Longer
recordings can add eligible time without fixing the underlying reference gap.

Completion: a per-component feasibility table, reconciled counts, explicit
provenance classes, and a clear list of extraction changes versus design decisions.
Likely files: `m6_replay.py`, `m6_cohort.py`, `m6.py`, `m6_revalidation.py`.

## 3. Use different datasets for different evidence

| Source | Appropriate role | Limitation and protection |
|---|---|---|
| Raw VitalDB longitudinal cases | Runtime missingness, clock/reference feasibility and paired controlled offsets/ramps | Surgical single-institution data; raw noise retained; monitor/cuff disagreement alone is not reviewed fault truth. [Official release](https://physionet.org/content/vitaldb/1.0.0/) |
| MIMIC-III Waveform Matched Subset | Independent ICU-source feasibility and later external research evaluation | ECG/PPG/ABP/numerics are not always concurrent. Check segment headers and cuff provenance; linked clinical records have separate access conditions. [Official description](https://www.physionet.org/content/mimic3wdb-matched/1.0/) |
| PulseDB v2 | Pressure-branch features/representation research, optionally ECG/PPG-only prediction | 5,361 files derived from VitalDB/MIMIC; bad segments removed. `T` is relative to a selected clip. Preserve gaps and parent-patient mappings; it is not longitudinal fault truth. MIMIC-derived data use ODbL/DbCL; Vital-derived data and subset information use CC BY-NC-SA 4.0. [Maintainer documentation](https://github.com/pulselabteam/PulseDB) |
| Independently reviewed clinical evidence | Genuine drift/no-drift/hypotension, onset and reference-quality adjudication | Still unavailable. Any institutional collection or clinical coordination requires separately approved scope. Do not request patient details in chat. |

Proposed storage envelope, to approve before downloads: **10 GiB pilot**, then
at most **40 GiB total incremental storage**, including partial downloads,
extraction, caches, features and reports. Keep at least **30 GiB free on D:**;
recheck space before each batch. Fetch only required tracks/cases. Full VitalDB
is listed at 95.4 GB uncompressed and would consume nearly the currently free
space before extraction overhead. [Release file sizes](https://physionet.org/content/vitaldb/1.0.0/)

Pilot design proposal: 24 new development patients, selected by predefined source
and availability strata, including weak/missing streams. Inspect bounded native
segments and, within budget, 4–6-hour/full available recordings. Do not select on
prediction error, replace unusable subjects or silently change selection criteria.
Use existing 24 inspected patients only for development, never as untouched test.

Before accessing model outcomes for a final cohort, register new patient IDs,
train/validation/test assignment, duration, source mapping and selection rules.
Group all repeat procedures and raw/cleaned derivatives of a person together.
If cross-source identity cannot be reconciled, exclude that material from the
claimed independent final test, or report independence as unverified.

Completion: budgeted manifest, license/access record, checksummed receipts,
simultaneous-channel/reference audit, exclusions with reasons and untouched-test
register. Pilot counts above are research logistics, not clinical power claims.

## 4. Compare partial-readiness designs in offline research

Proposal only; existing runtime parameters and clinical guards remain unchanged.

- **Event-based cuff component:** compare contemporaneous line evidence at a
  verified cuff acquisition. Keep the locked five-second score schedule while
  avoiding counting repeated exposure to one reference as many independent
  clinical observations. Unknown acquisition provenance remains explicit.
- **Morphology component:** consider a separately qualified waveform baseline
  with its own valid-duration/quality requirement, independent of cuff cadence.
  Without an independent reference it signals shape change, not confirmed drift.
- **Physiology residual component:** compare a baseline from clean ECG/PPG/HR
  with explicit calibration/reference requirements and uncertainty. Frozen
  baselines must not adapt away slow faults; age, gaps and change points matter.
- **Combined assessment:** require the evidence appropriate to that combination.
  Do not make every component inherit one all-or-nothing gate. Preserve urgency
  first, partial readiness, abstention and uncertain cause.

Predeclare independent-reference requirements and baseline-validity duration.
Compare the unchanged scorer with each proposed component separation, one factor
at a time. Do not lower 179 windows, extend freshness or weaken pressure guards
solely to raise pass counts. Baseline age/gap policies and new score semantics
require an explicit design decision and decision-layer review before runtime use.
Use the existing v1 `extra` extension only with agreed consumer semantics; do not
rename fields/topics or introduce new verdicts.

Completion: offline paired coverage/delay/safety comparisons including unavailable
windows, and a written decision on each proposed readiness mode. Full clinical
readiness remains pending without genuine reviewed truth.

## 5. Improve features before escalating model complexity

Keep the frozen ridge, forest and unchanged runtime as reproducible comparators.
Run controlled patient-separated comparisons with a fixed training population,
preprocessing and target so a family change is not confounded with more data.

1. Improve causal signal-quality assessment, ECG-to-PPG beat matching, HR
   availability and amplitude handling. Preserve pressure units for cuff gaps;
   do not normalize away offsets that M6 must detect. Avoid future samples and
   whole-record zero-phase filtering in a live-compatible pipeline.
2. Compare HR/timing/PPG-only predictors against the existing ART-amplitude
   predictor. The latter depends on the signal being checked. Test an ART-only
   fault while holding independent channels fixed; record how much the prediction
   moves. PPG gain/contact changes are nuisance factors, not true BP labels.
3. Compare robust episode calibration, ridge and a small tree model on the same
   data. Review low-pressure tails and the previously observed patient regression.
   Use patient weighting and report both macro and window metrics.
4. Add a small causal temporal model only if enough independent longitudinal
   subjects and a reproducible simpler baseline justify it. Compare identical
   features/data and account for extra compute/deployment costs on LinuxONE.
5. Compare Page-Hinkley with a justified causal change detector under an equal
   validation false-alarm budget. Persistence, hysteresis and uncertainty must
   be selected on validation, with measured impact on delay and coverage.

Use positive/negative offsets, slow ramps, missing cuff, dropouts and clock/gain
perturbations. Add physically motivated over/under-damping fixtures with documented
transfer behavior, start-up transients and causality; 40% amplitude attenuation
is not a validated physical damping model. Synthetic fault labels establish
injection provenance only, not clinical fault truth or malicious intent. Kartik
owns network/attack evidence; M6 must not infer intent from its score.

Completion: predeclared candidate register, same-data ablations, failed hypotheses,
patient/slice metrics, latency measurements and reproducible non-executable
weights. No research winner automatically replaces the runtime scorer.

## 6. Freeze and evaluate once on new patients

Use development and validation for features, quality cutoffs, baseline modes,
event grouping, thresholds and model selection. Register those choices, source
hashes and weights before final waveform/label inspection. Retire every inspected
test cohort from future untouched-test claims.

Report all patients, durations, missing/unusable windows and absence of required
labels. Give per-patient results, patient-cluster intervals, subgroup errors,
pressure tails and paired improvements. Count detections attributable to injection
only where the original paired window was not already positive. Include onset
windows with abstention and non-detection; conditional assessable-only performance
must appear alongside end-to-end event performance and coverage.

Clinical drift precision/false alarms and hypotension false-drift safety require
qualified review, independently supported pressure/fault evidence and verified
onsets. Zero genuine safety observations remains unevaluated. Singhal reviews
the model/decision integration; his project role does not establish clinician
qualification. Broader external validation and intended-setting review remain
separate from synthetic/software success.

Completion: frozen protocol and one-time new-patient report. Any post-test change
starts a new experiment and needs a new final test; preserve the failed run.

## 7. Preserve workflow compatibility and close each integration gate

Implementation follows explicit authorization of the concrete scoped proposal.
Use new output directories and preserve prior state, weights and dirty files.
Relevant boundaries are `m6.py`, replay/evaluation/training modules,
`m6_persistence.py`, `presentation.py`, strict contracts and their fixtures/tests.

- Keep v1 topic/field/enumeration compatibility, 125 Hz causal 10-second windows
  at five-second hops, explicit nulls and evidence-index semantics.
- Keep M6 disabled by default and rejected as unreviewed research in design-real.
  Version changed algorithms; require reviewed episode/calibration transitions.
- Preserve deterministic user/team lines <=160 characters, explicit supported
  urgency and complete typed model JSON. No LLM chooses live wording/actions.
- Preserve primary-screen alert state, secondary phone delivery, BOTH independence,
  three-step high ladder, idempotent callbacks, separate acknowledgement, Patient
  NOT OK urgency, and no cancellation by NORMAL before acknowledgement.
- Preserve TLS/authentication, policy checks, append-only audit, atomic state/outbox,
  duplicate/restart behavior and linked undo. No treatment or monitor commands.

Run meaningful regression checks for changed behavior, then the repository's
static checks, dev+research tests with disposable PostgreSQL and VitalDB configured,
and installed-package inference/migrations/output compatibility. Report skips
honestly. Cache/build/test temporary writes stay on D: after path authorization.
Measure full 8–12-bed LinuxONE and delivery latency separately from scorer calls.

| Owner | Exact external input/check still required |
|---|---|
| Aditya Singh | Broker TLS/ACL/auth, DB ownership/access, protected roster, monitor/episode/clock and actual cuff-event provenance; agreed assignments/waveform/agent-event interfaces; ward/alert-to-backend-to-/ws screen delivery |
| Aditya Singhal | Aligned M3/M5 semantics and M6 abstention/evidence interpretation; verdict fixtures; score-to-decision integration and approved selection/evaluation protocol |
| Kartik | Independently timed fault/slow-attack fixtures, aligned network evidence and typed A2/A3/A4 interfaces; containment must preserve patient alert |
| Antara/Antra screen teammate | Stable alert/output rendering, protected staff mapping, real screen and Telegram callbacks, one ladder updated by either channel; naming clarification without wire changes |
| Qualified reviewers/institution | Reviewed drift/stable/genuine-hypotension labels, independent fault/reference evidence, operating criteria and any clinical collection authorization |

The next implementation proposal should be the **quality/provenance audit and
bounded data pilot**, with explicit inputs, storage costs and result schema.
Keep live/team and clinical gates open until each is observed passing. This plan
does not authorize new clinical collection, deployment, contract-breaking changes,
teammate-model training, commit or push.
