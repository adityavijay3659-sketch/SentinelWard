# Real-data training and Phase 0–3 verification

This run downloaded real recordings and trained an offline research model. It
did **not** establish that the runtime M6 drift detector is ready for patients.
Runtime checks were deliberately not relaxed to make the experiment pass.

## Source and fixed cohort

Source: [VitalDB official public API](https://vitaldb.net/docs/?documentId=API%2FWeb_API_OpenDataset.md),
[dataset release and attribution](https://physionet.org/content/vitaldb/1.0.0/).
The API metadata returned 6,388 cases and 486,449 tracks during this download;
these counts describe the response, not an assertion that all release tracks
were downloaded. License: CC BY 4.0; attribute the VitalDB authors when using it.

The pilot selected 12 distinct subjects with required track availability and
case duration >=3,600 seconds, using seed 20261009. Repeated operations for the
same subject cannot enter different groups. Selection used metadata, not test
outcomes. Four subjects each were assigned to train, validation and test. Each
case contributes its first hour, including missing channels and unusable periods.
This is a small surgical cohort, not external ward validation or a whole-dataset run.

Downloaded: 96 bounded track files plus two metadata files; all 98 receipts were
rechecked against SHA-256. Stored size: 658,585,293 bytes, about 628 MiB. The
downloader keeps time/sample metadata, limits each request, uses verified HTTPS,
bounded retries and atomic partial-file promotion, and verifies cached files.
Raw recordings, subject IDs, feature tables and weights remain on D:, outside Git.

## Experiment A: actual runtime M6

Unchanged runtime settings: 179 usable baseline windows, 120-second cuff age,
10 mmHg gap, and existing deterioration precedence. Repeated monitor NIBP values
are held observations, not newly acquired cuff readings; they must not refresh
cuff age. Even a changed value has only a monitor observation timestamp, not
proof of the cuff's acquisition time. Identical remeasurements cannot be recovered
from these tracks. This limitation is conservative and remains explicit.

Across 12 cases / 8,628 aligned reference windows:

| Observed result | Count |
|---|---:|
| Insufficient data | 6,965 |
| Emergency-compatible research output | 1,545 |
| Baseline-collection windows | 118 |
| Subjects completing the 179-window baseline | **0 / 12** |

The held-out cases collected 35, 0, 2 and 32 baseline windows respectively.
Validation could not select a useful threshold. The default 0.6 was frozen and
the failure recorded before processing test cases. Because injection begins only
after successful baseline collection, **no injections were activated**. Drift
sensitivity, false-positive rate and detection delay are therefore **not measured**;
an empty metric set is not a zero-error result. These data do not close the
runtime readiness or clinical safety gate. Emergency-compatible counts are
algorithm outputs, not adjudicated diagnoses.

## Experiment B: offline real-data model training

This separate research experiment fits a population ridge regression using HR,
ECG-to-PPG timing proxy and arterial pulse amplitude. The target is recorded
Solar8000 arterial monitor MAP, observed at/before the last frame's timestamp
and no more than five seconds old. It is a device measurement, not a reviewed
diagnosis or a cuff substitute. Pressure contributes to the input amplitude;
this experiment cannot demonstrate independence from a drifting pressure sensor.

Preprocessing centres/scales and coefficients are fitted only on training
subjects. Ridge candidates 0.1, 1, 10 and 100 were declared before testing;
validation MAE selected 100. Weights and their hash were frozen before test
features were extracted. No test-label tuning or post-test retraining occurred.

| Split | Subjects | Usable windows | MAE, mmHg | RMSE, mmHg |
|---|---:|---:|---:|---:|
| Train | 4 | 2,045 | 13.57 | 18.42 |
| Validation | 4 | 1,622 | 11.96 | 16.22 |
| Held-out test | 4 | 2,311 | **9.05** | **11.77** |

Held-out bias: +5.00 mmHg; patient-macro MAE: 9.15 mmHg. The constant training-mean
baseline scored 11.08 mmHg test MAE, but did better on validation (10.56 versus
11.96). Direct arterial waveform averaging scored 4.36 mmHg test MAE, better
than this regression. The predefined held-out improvement over the constant
baseline occurred; this is not evidence that the regression is the best model
or clinically acceptable. Four test subjects are too few for such a claim.

Of 8,628 aligned windows, 5,978 had usable regression inputs/target; 2,490 had
unusable features and 160 had missing/unusable targets. The quality report retains
these losses. There were 1,113 usable windows with monitor MAP <=65: these are
correlated **review candidates**, not 1,113 confirmed hypotensive episodes.

Weights: `m6-regression-20261009-run1/model.json` in the artifact root below.
SHA-256: `e0a3bb4b6c279981031adfaebad373e59b3cd447b7ece7e7d68a5fec468b6c43`.
The exact scoring/training source snapshot was retained and verified against
the experiment's recorded source hashes. Later source cleanup and input-path
validation do not change the recorded model; a future modelling experiment must
use a new registered cohort/test set rather than tune against this result.

These weights have a distinct offline artifact type. They are **not loaded into
the service**, do not replace patient-specific runtime baselines, and cannot be
passed off as a reviewed M6 calibration artifact. M1–M5 teammate models were
not trained or substituted.

## Software and connectivity

The first complete release rerun exposed a test-isolation defect: an existing
M6 test counted other beds' pending outbox entries. It now selects only its own
bed and window. Final evidence is the later successful rerun, not that failure.

The checks exercise contracts, every output audience, engine routing, policy,
authenticated API behavior, audit/idempotency, outbox retries, alert lifecycle,
escalation/acknowledgement timers, restart/checkpoints and M6 transactions. The
new integration test replays 30 actual recording frames through the v1 contract
and PostgreSQL handler, replaces the handler mid-stream, rejects a duplicate,
and verifies five unique QoS 1 score outbox entries and full machine JSON.
The publisher boundary tests are not a live broker delivery demonstration.

| Connection | Measured status |
|---|---|
| PostgreSQL 17.10, local disposable lab | Connected; migrations 0001–0003 and checkpointer initialized |
| LangGraph/SQL checkpoint + APScheduler | Exercised by PostgreSQL-backed regression tests |
| Installed dependency sets | Compatible: 73 development / 60 installed-package distributions |
| Configured MQTT 127.0.0.1:8883 | TCP unreachable; TLS CA and credentials not configured; authenticated pub/sub pending |
| Backend | URL/token not configured; live health and integration pending |
| Telegram | Bot token/recipient map not configured; phone delivery and callbacks pending |
| LinuxONE / physical monitors / teammate models / screen | Not connected or verified in this run |

Connectivity auditing performs read-only probes. No clinical messages, device
commands or staff Telegram messages were sent. TLS/authentication requirements
and the phone-as-backup architecture remain unchanged. Runtime M6 is still
disabled by default; clinical deployment remains blocked by the existing gate.

## Actual short output

Examples from the real-recording replay (the epoch is deliberately zero, so these
are **replay-clock times**, not patient date/time):

```text
USER 00:00:05 UTC | B01 | URGENT: PATIENT CHECK | Possible patient deterioration; do not dismiss as sensor drift | RESEARCH; STAFF REVIEW
TEAM 00:00:05 UTC | B01 | URGENT M6 PATIENT CHECK | Possible patient deterioration; do not dismiss as sensor drift | RESEARCH ONLY
```

USER/TEAM prefixes identify the examples here; they are not part of the actual
rendered line. Each human/team output remains one physical line <=160 characters.
Machine consumers receive full typed v1 JSON, with `inputs_sufficient`,
`emergency_compatible` and `clinical_validation: pending`; no truncated JSON or
display-text parsing is introduced. There was no drift example from this run.

## Artifacts and reproduction

Artifact root: `D:/SentinelWard-Data/VitalDB`.

- `m6-20261009-run1/`: verified source subsets, receipts and frozen selection.
- `m6-experiment-20261009-run1/`: retained failed initial parser attempt.
- `m6-experiment-20261009-run2/report.json`: strict runtime readiness failure.
- `m6-regression-20261009-run1/`: plan, train/validation/test feature tables,
  validation selection, frozen weights, report and exact execution source.
- `connectivity-20261009.json`: read-only current-configuration audit.
- `phases-tests-verified-20261009.xml`: prior successful 106-test run; latest
  final test evidence is added below after the path-validation regression.

```powershell
# Existing download resumes only after checksum verification.
python -m sentinelward.m6_realdata download --root D:/SentinelWard-Data/VitalDB/m6-20261009-run1 --count 12 --duration 3600
# Research execution requires a new output directory. Do not retune on this held-out set.
python -m sentinelward.m6_realdata experiment --root D:/new-reviewed-cohort --output D:/new-runtime-run
python -m sentinelward.m6_training --root D:/new-reviewed-cohort --output D:/new-training-run
python -m sentinelward.connectivity --output D:/new-connectivity-report.json
```

The remaining M6 gates require recordings with verified cuff acquisition times
and enough usable baseline coverage, adjudicated drift/hypotension labels, an
independent new held-out cohort, and teammate/device/ward integration. A different
open dataset alone cannot verify staff delivery, credentials, devices or the
clinical workflow. Phase 0–2 external acceptance gates remain pending as before.
No commit or push was made.

## Final verification results

Final full suite with both PostgreSQL and the downloaded VitalDB root configured:
**107 passed, 0 failed, 0 skipped, 35.82 seconds**. Evidence:
`D:/SentinelWard-Data/VitalDB/phases-tests-final2-20261009.xml`.
Ruff lint passed, Ruff verified 86 formatted files, and mypy passed 36 source
modules. Development dependency compatibility passed for 73 distributions; the
fresh wheel environment passed for 60 locked distributions.

Final wheel: `D:/SentinelWard-Realdata-ReleaseDist-20261009/sentinelward-0.3.0-py3-none-any.whl`.
Installed environment: `D:/SentinelWard-Realdata-WheelTest-20261009`.
Wheel SHA-256: `71075e7ec0ce8ba7730752481d6653d731ce8edacb46190b9c2556571840422e`.
Outside the checkout, the installed package applied all three migrations to a
fresh disposable database, initialized the LangGraph checkpointer, passed the
duplicate workflow smoke test, and validated the saved real-data model/hash.
These are local software checks, not a live broker, phone or clinical acceptance test.

Cleanup removed only `sentinel_realdata_verify_20261009` and
`sentinel_realdata_wheel_20261009`, after confirming no active clients. They are
recreatable from migrations/fixtures. PostgreSQL was restored to its original
stopped state; recordings, weights, test evidence and installed environments
remain available. The earlier connected status describes the verification run.
