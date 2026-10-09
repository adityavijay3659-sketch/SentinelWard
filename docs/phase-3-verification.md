# Verification evidence — 9 October 2026

Latest: [M6 0.3.1 revalidation and clinical evidence still needed](m6-revalidation-2026-10-09.md).
The package/test results below are historical 0.3.0 evidence, not the current release.

Later run: [real-data training and connectivity evidence](real-data-verification-2026-10-09.md).
The synthetic-only evidence below is historical. The later runtime real-data
check failed baseline readiness; the separately trained regression is offline
research and does not close the clinical gate.

Package: SentinelWard 0.3.0, Python 3.12.14, Windows x86-64. Phase 3 scope was
checked against the team's Drive documents before implementation. Current
changes remain local; no commit or push was made during this implementation.

## Final checks

| Check | Result |
|---|---|
| Complete pytest suite with PostgreSQL enabled | 92 passed, 0 failed, 0 skipped; 25.67 seconds |
| Ruff lint | All checks passed |
| Ruff formatting | 54 files already formatted |
| Mypy | No issues in 33 source files |
| Tracked diff whitespace | Passed; Windows line-ending notices only |
| Coverage, statements and branches combined | 74% overall; M6 scorer 94%; presentation 95% |
| Fresh wheel, locked dependency installation | Passed; all 60 installed packages compatible |
| Outside-checkout package import | Installed site-packages version 0.3.0 |
| Fresh database migrations | 0001, 0002, 0003 applied successfully |
| Installed checkpointer initialization | CHECKPOINTER_INITIALIZED |
| Installed duplicate workflow smoke test | SMOKE_TEST_PASSED |
| Installed M6 synthetic harness | Completed; research gate remains pending |

The suite covers missing/gapped/late frames, stale cuff, nonfinite samples and
metadata, timestamps, baseline warmup/freeze, offset/damping, deterioration
precedence, peer hints, sequence/device/episode mismatch, patient split leakage,
artifact integrity, duplicate evaluation, each output audience and existing
Phase 1/2 regression behavior. PostgreSQL tests inject a failure after writing
M6 state and before inserting its score: the transaction rolls back. A restarted
handler receives 12 concurrent copies of the final frame and creates one outbox
entry. MQTT adapter-boundary delivery uses QoS 1 and retain=false.

These are local checks. There was no live LinuxONE deployment, hospital device,
real broker credential test, actual Telegram phone delivery or end-to-end screen
verification. Overall coverage is not 100%; the untested external paths remain
visible in the coverage report and phase checklists.

## Installed synthetic harness measurements

Twelve distinct bed/episode scenarios ran sequentially: six validation and six
held-out synthetic scenarios. They share generated waveform templates; the
patient separation verifies software controls, not population generalization.
Cases cover stable pressure, a +15 mmHg offset, a five-minute +15 mmHg ramp,
pulse attenuation, the same offset with mock tampering evidence and hypotension.

| Measurement | Recorded result |
|---|---|
| Held-out synthetic windows / episodes | 138 / 6 |
| Positive drift/tampering windows | 108 |
| True positives / false negatives | 68 / 40 |
| Stable/hypotension false positives | 0 / 30 negative windows |
| Window drift sensitivity | 62.96% |
| Detected drift events | 4 / 4 |
| Event detection delays | 10, 10, 10, 210 seconds |
| Hypotension false drift | 0 / 15 windows, from one synthetic episode |
| Validation-selected threshold | 0.65 evidence index |
| Sufficient drift-input windows | 123 / 138 |
| Cuff-gap-only comparator true positives | 53 / 108 positive windows |
| Median / p95 / max scorer call latency | 0.021 / 8.452 / 25.862 ms |

Forty positive windows were missed, chiefly while the slow ramp was below the
cuff-gap/evidence threshold. Event detection and window sensitivity answer
different questions; both are reported. The synthetic sample is small and
formulaic. Zero failures in one episode has a 95% one-sided patient-level upper
bound of 95%, so this cannot establish real-patient safety. Latency measures
only the sequential in-process scorer, excluding database, broker and transport.
Offsets of different sizes/signs, 30-minute ramps, real damping waveforms and
independent adversarial inputs still need the actual validation/evaluation pack.

## Reproducible artifacts

- Wheel: `D:/SentinelWard-Phase3-Dist-20261009/sentinelward-0.3.0-py3-none-any.whl`
- Wheel SHA-256: `9bb16cb72d0b907de6f63ce3d76cf3b3eedcae9dfa087fd2643bd1de60f6af32`
- Installed test environment: `D:/SentinelWard-Phase3-WheelTest-20261009`
- Frozen dependencies: `D:/SentinelWard-Phase3-Locked-Requirements-20261009.txt`
- Measured report: `D:/SentinelWard-Phase3-Wheel-Synthetic-20261009.json`
- Synthetic artifact ID: `fd8e81388c63b8353694465140f6ff2b5c0ee62cb0826a59805ae3ca265dd16b`
- Synthetic held-out hash: `de62f4736325f29686831929e55065111e10a82ab50592e96249d8c2d7e0de71`

The two task-created disposable verification databases were removed after the
checks. The local PostgreSQL server was restored to its original stopped state.
Reports, wheel and test environments are retained; migrations and fixtures can
recreate the verification databases.

No real patient dataset or reviewed calibration artifact was supplied in this
turn. Runtime M6 therefore defaults to disabled; enabled test/demo scoring is
explicitly marked research. The real-data and whole-team gates stay unchecked.

## Actual audience examples

```text
USER 00:16:10 UTC | B08 | WARNING: POSSIBLE DRIFT | Pressure disagrees with cuff and baseline; sensor review needed | RESEARCH; STAFF REVIEW
TEAM 00:16:10 UTC | B08 | M6 DRIFT 0.85 | Pressure disagrees with cuff and baseline; sensor review needed | RESEARCH ONLY
USER 00:16:10 UTC | B09 | URGENT: PATIENT CHECK | Low cuff pressure observed; immediate patient review needed | RESEARCH; STAFF REVIEW
TEAM 00:16:10 UTC | B09 | URGENT M6 PATIENT CHECK | Low cuff pressure observed; immediate patient review needed | RESEARCH ONLY
```

The `USER`/`TEAM` prefixes identify examples here and are not included in the
renderer output. Each actual human/team line is one physical line <=160
characters. Model consumers receive the complete v1 score, including evidence,
input sufficiency and validation state; no display prose is parsed as a contract.
