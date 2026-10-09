# M6 research revalidation — 9 October 2026

Scope: Aditya's M6 only. No teammate model was trained or changed. The user
confirmed that reviewed drift/hypotension labels and verified cuff acquisition
timestamps are not available and requested research validation with the remaining
clinical evidence listed. Changes remain local; no commit or push was made.

Research reevaluation completed, but clinical readiness did **not** pass.
All 12 new recordings ran; full baseline readiness remains **0/12**. The new
gap-only path is available on supported windows without pretending the combined
baseline scorer is ready. Offline regression improved on the paired held-out
comparison, but its uncertainty and one patient-level regression remain visible.

## Diagnosis and fixes

The earlier `0/12` measured full baseline readiness, not whether cases executed.
All earlier recordings produced scores. Of 5,978 usable feature windows,
5,454 (91.2%) lacked a fresh cuff reference. Other windows were rejected by
pressure disagreement or patient-review guards. The experiment also waited for
baseline completion before injecting drift, leaving those tests unevaluated.

The old scorer required the complete 179-window baseline before assessing an
ART/cuff disagreement. A reproduced cold-start 100/85 mmHg fixture returned
`insufficient_data` before the fix. The same fixture now returns a research
`drift` score of 0.75, explicitly marked `assessment_path=cuff_gap_only` and
`baseline_ready=false`. No regression prediction, Page–Hinkley result or clinical
probability is fabricated. A 10–12 mmHg gap below the configured evidence
threshold remains an incomplete assessment, not a normal-patient verdict.

High monitor alarms, low cuff/arterial pressure and substantial pressure falls
retain priority over drift. Cuff freshness, missing waveform rejection, the
179-window baseline requirement, authentication and TLS were not relaxed.
Gap-only windows do not enter the baseline. The scorer reports required/collected
baseline counts, assessment path, availability and its pending clinical gate.

The new experiment injects changes at a fixed 15-minute onset, independently of
baseline completion, and saves every score window, including abstentions.
One validation recording has no usable arterial waveform and zero regression
target windows. The original run stopped on its strict coverage assertion. A
pre-held-out resume amendment preserves that subject as unevaluable, reports
validation coverage as 3/4, and keeps the split/candidates/threshold unchanged.
It does not replace the missing subject with a better-performing recording.
Resume is deliberately restricted to before model freeze; it cannot refit after
held-out evaluation has started. Source snapshots and dataset hashes are retained.

## Data and locked protocol

The source is the public, de-identified [VitalDB dataset](https://physionet.org/content/vitaldb/1.0.0/),
licensed CC BY 4.0. It records surgical patients at one institution; it is not a
representative ward population or an adjudicated sensor-drift dataset. Its
recordings support research, not an inference of clinical safety for this system.

The new cohort contains 12 subjects, with the first 7,200 seconds per case and
no overlap with any of the earlier 12 subjects. Numeric reference-availability
screening examined 177 subjects before selecting 12. The fixed criterion was
at least 200 five-second windows after 900 seconds with a changed cuff reference
aged at most 120 seconds and recent arterial numeric data. It did not select on
prediction error, low-pressure labels or drift outcomes. Nevertheless, screening
introduces reference-availability bias and did not guarantee waveform usability.

The frozen screening plan's descriptive text mistakenly called these windows
"changed cuff observations." Its numeric field and executed algorithm always
meant 200 five-second windows; the original artifact is preserved and this note
records the wording correction. There were not 200 distinct cuff acquisitions.
Changed cuff tuples are a conservative replay proxy, not verified acquisition
timestamps; identical repeated true measurements may be undercounted.

The split was frozen as four training, four validation and four held-out subjects.
The previous 12 subjects, including the old test group, were explicitly retired
to development. Training uses 16 subjects / 10,408 windows; validation metrics
use 3/4 subjects / 3,084 windows; test metrics use 4/4 subjects / 4,089 windows.
No patient's windows cross the new split boundaries.

The offline target is the recorded monitor's `Solar8000/ART_MBP`, not adjudicated
true blood pressure. Inputs remain HR, ECG-to-PPG timing proxy and pulse amplitude;
current arterial MAP is not an input to this physiology predictor. The old ridge
is compared on exactly the same new held-out windows. Both training population
and model family changed, so improvement is not a pure architecture ablation.

Seven candidates were declared before held-out testing: ridge strengths
0.1/1/10/100 and 64-tree forests with depth/leaf settings 6/20, 10/20 and 10/50.
Validation patient-macro MAE selected forest 10/50 (10.0896 mmHg). Forest training
weights each patient equally, uses seed 20261009 and exports bounded, validated
numeric JSON rather than executable pickle weights. Serving JSON inference needs
no scikit-learn. Training uses optional pinned `scikit-learn==1.9.1`.
See [official persistence guidance](https://scikit-learn.org/stable/model_persistence.html)
for the execution risks of pickle-based artifacts.

The selected model was frozen and hashed before reading the new held-out
waveforms. The M6 drift evidence threshold stayed at 0.6 and was **not** tuned
on these unreviewed recordings. The offline forest is not installed into the
runtime episode-baseline scorer or accepted as a calibration artifact.

## Held-out regression results

| Metric | Old ridge, same new test windows | Selected forest |
|---|---:|---:|
| MAE, mmHg | 10.0994 | 8.5539 |
| RMSE, mmHg | 13.1159 | 11.8293 |
| Prediction-minus-target bias, mmHg | -2.0347 | -0.0686 |
| Independent subjects / usable windows | 4 / 4,089 | 4 / 4,089 |

Paired window-weighted MAE reduction: **1.5455 mmHg**, or approximately 15.3%.
The earlier 9.0544 mmHg MAE came from a different test cohort and is not the
valid paired baseline for this result.

Three patients improved; one worsened from MAE 9.1894 to 11.7151 mmHg.
Patient-macro MAE reduction is 1.7922 mmHg. A paired patient-level percentile
bootstrap (2,000 draws, seed 20261009) gives a 95% interval of **-1.0557 to
3.9398 mmHg**. It includes zero: robust improvement is not established by four
subjects. Overlapping windows were not treated as independent patients.

Direct waveform MAP has MAE 5.4946 mmHg on the same targets, better than the
forest. That comparator uses the arterial signal that M6 is checking; it is not
an independent physiological reference or a shortcut used by the trained model.
None of these MAE values establishes clinical blood-pressure accuracy.

## Drift tests now evaluated, with coverage and attribution

Each held-out variant has 5,036 post-onset windows from four subjects. The table
counts additional predictions only where the paired original recording was not
already drift-positive. A prediction already present in the original recording
is not credited as detecting the injected change.

| Controlled variant | Additional prediction windows | Subjects with additional prediction | Sufficient drift-input windows |
|---|---:|---:|---:|
| +15 mmHg offset | 102 | 4/4 | 169/5,036 (3.36%) |
| -15 mmHg offset | 36 | 3/4 | 88/5,036 (1.75%) |
| Five-minute +15 mmHg ramp | 99 | 3/4 | 170/5,036 (3.38%) |
| Thirty-minute +15 mmHg ramp | 39 | 3/4 | 132/5,036 (2.62%) |
| Pulse amplitude attenuated to 40% | 5 | 1/4 | 104/5,036 (2.07%) |

For the +15 mmHg offset, first additional-prediction delays were 15, 165, 665
and 1,305 seconds. Reference availability and patient-review precedence limit
coverage and delay. These are controlled perturbation responses, **not clinical
sensitivity**, and they do not establish a cause such as tampering.

The original recordings already had 87 drift predictions; without reviewed
truth they cannot be labelled false positives or confirmed drift. The synthetic
coupled low-pressure control produced **0/5,036 drift predictions**, 4,843 urgent
patient-check windows and 193 remaining unavailable-input windows. It does not
substitute for a genuine, clinician-reviewed hypotension safety set.

Across all 12 reference recordings, 17,268 windows were assessed, with 414
explicit gap-only assessment windows. Baseline counts were 111/14/89/70 for
training, 76/43/6/0 for validation and 89/48/0/1 for testing, versus 179 required.
Full combined baseline readiness is still **0/12**. Amplitude/combined drift
coverage remains inadequate on this subset. We did not lower safety guards or
fabricate cuff events to turn this into a pass.

Per-case p95 scorer-call times ranged from 0.203 to 9.458 ms across the seven
variants. These sequential in-process measurements exclude CSV loading,
PostgreSQL, MQTT and network/phone latency; they are not ward throughput results.

## Output and team compatibility

Locked v1 wire shapes/topics remain unchanged. Human/team views stay one physical
line, at most 160 characters, with deterministic wording. Urgent patient review
retains priority; partial gap assessments explicitly identify their limitation.
The following are actual renderer outputs from generated verification inputs,
not live patient messages; replay zero timestamps represent the case-relative clock.

```text
USER 00:00:00 UTC | B01 | WARNING: POSSIBLE DRIFT | ART and cuff disagree; combined assessment unavailable; review patient and sensor | RESEARCH; STAFF REVIEW
TEAM 00:00:00 UTC | B01 | M6 GAP-ONLY DRIFT 0.75 | ART and cuff disagree; combined assessment unavailable; review patient and sensor | RESEARCH ONLY
```

The `USER`/`TEAM` prefixes identify these examples, not renderer content.
Below-threshold gap output says `WARNING: PRESSURE GAP`, not `DATA MISSING`.
Low pressure says `URGENT: PATIENT CHECK`. Machine consumers receive the complete
v1 score with `assessment_path`, actual measured gap, evidence-index semantics,
baseline availability, cuff age, and `clinical_validation=pending`. Display prose
must not be parsed as a machine contract. This policy applies across all phases.

Package/scorer versions are 0.3.1 / `m6-research-0.3.1`. Reusing an old stored
episode or old calibration artifact is rejected. Before enabling the upgraded
research scorer, obtain a reviewed new opaque episode ID with a start timestamp
later than the old episode's last frame; do not silently delete patient state.
No new SQL migration is required beyond the existing three migrations.

## Verification and connectivity

Final checks used Python 3.12.14 and PostgreSQL-backed tests with the local
VitalDB integration enabled. No test was counted as passing without execution.

| Check | Result |
|---|---|
| Complete pytest suite | 123 passed, 0 failed, 0 skipped; 42.15 seconds |
| Ruff lint / formatting | Clean / 95 files already formatted |
| Mypy | Clean, 40 source modules |
| Locked core wheel dependency check | All 60 installed packages compatible |
| Installed package outside checkout | 0.3.1; all 40 source-module hashes match |
| Fresh database migrations / checkpointer / duplicate workflow smoke | Passed |
| Installed cold-gap, below-threshold gap and urgent low-pressure outputs | Passed; one line, <=160 characters |
| Installed frozen forest inference | 100 saved predictions match within 1e-9, without scikit-learn |
| Data and original/resumed scorer source integrity | 921 receipts and source hashes verified |

Regression tests cover cold start, missing/stale reference, low-pressure
precedence, version reset, safe JSON inference, source integrity, explicit
missing-subject coverage, patient-level uncertainty and paired detection
attribution, alongside existing Phase 0–3 contracts and automation tests.

The read-only connectivity audit reached local PostgreSQL 17.10. The configured
MQTT TCP endpoint is unreachable, with no CA/credentials configured; backend
URL/token and Telegram token/recipient mapping are absent. Authenticated broker
publication, real backend integration and actual phone delivery remain pending.
TLS/authentication were not bypassed. External effects remain simulated, M6
defaults to disabled, and no clinical messages or device commands were sent.

After verification, the two task-created disposable databases
`sentinel_m6_v2_verify_20261009` and `sentinel_m6_v2_wheel_20261009` were removed
after confirming no other clients were connected. PostgreSQL was restored to
its original stopped state. These test databases can be recreated from the
migrations and fixtures; datasets, model weights, reports and environments remain.

## Clinical evidence still required

- Clinician-adjudicated genuine drift, stable/no-drift and hypotension episodes,
  including onset times and independent evidence of sensor malfunction.
- Verified cuff acquisition timestamps, monitor identity, episode lifecycle,
  stream clock alignment and reference measurement quality. A changed-value
  replay proxy is not enough for clinical reference freshness.
- Representative ward recordings with sufficient baseline/reference availability,
  missing-data scenarios, pressure ranges, patient diversity and device variants;
  independent external validation beyond this screened surgical subset.
- An agreed clinical evaluation protocol and acceptance criteria for missed
  deterioration, false drift alarms, delays, abstention and escalation burden.
  Select thresholds on reviewed validation data, then freeze and test once on
  new independent patients with adequate sample size and uncertainty reporting.
- Genuine hypotension false-drift review, clinical workflow/override sign-off,
  live LinuxONE load/restart testing and authenticated team integration with
  screen plus the phone backup channel.

No treatment recommendation, production calibration, regulatory approval or
clinical-readiness claim is made. Research validation is completed and reported;
several readiness gates failed or remain unevaluated, rather than all passing.

## Reproducible artifacts

Bulk data, model weights, reports, environments and caches are outside Git on D:.

- Cohort: `D:/SentinelWard-Data/VitalDB/m6-20261009-independent-v2`
- Experiment: `D:/SentinelWard-Data/VitalDB/m6-revalidation-20261009-v2`
- Protocol/history: `plan.json`, `resume-plan.json`, original/resumed execution-source snapshots.
- Frozen weights: `selected-model.json`; SHA-256
  `fcf46ebbc250df079fa1bb84137903a57c15d9df5a3ed037da8c3200e9a5d5ef`.
- Results: `report.json`, `validation.json`, `heldout-predictions.json`, per-case
  features/quality/scores, and `clinical-review-candidates.json`.
- Audit: `audit-final.json`, with patient-bootstrap uncertainty, paired additional
  detection delays, verified source hashes and **921 dataset receipts /
  1,187,600,265 bytes**. Earlier `audit.json` and `audit-v2.json` are preserved;
  the first lacks the later additional-detection attribution fields. No audit
  refits or retunes.
- Review candidates: 1,494 low recorded monitor-MAP windows among the usable
  regression windows, not a complete hypotension census or adjudicated labels.
- Connectivity: `D:/SentinelWard-Data/VitalDB/m6-v2-connectivity-20261009.json`.
- Final tests: `D:/SentinelWard-Data/VitalDB/m6-final-handoff-tests-20261009.xml`.
- Wheel: `D:/SentinelWard-M6-Handoff-Dist-20261009/sentinelward-0.3.1-py3-none-any.whl`;
  SHA-256 `271fb83e798d66f35828d1b9e7c4895352b8bd86137b56af7a068ebe61286c0e`.
- Isolated installed core environment: `D:/SentinelWard-M6-V2-WheelTest-20261009`;
  frozen hashed dependencies: `D:/SentinelWard-M6-V2-Core-Requirements-20261009.txt`.

For a new experiment, use a **new output directory**; do not overwrite or tune
against this held-out test. The source snapshot records the exact executed
versions, including the original eight cached case runs and the resumed four
held-out runs. Later reporting/snapshot-helper edits do not change the frozen
model or recorded predictions.

```powershell
uv sync --extra dev --extra research
uv run python -m sentinelward.m6_revalidation --root D:/new-cohort --previous-regression D:/previous-regression --output D:/new-experiment
```

The completed cohort and test must not be repurposed as a fresh independent
test after inspecting these outcomes. Keep all credentials and patient data out
of the repository and shared messages.
