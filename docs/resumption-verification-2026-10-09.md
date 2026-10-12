# SentinelWard resumption verification — 9 October 2026

Scope: read the complete 20-section master handoff, inspect the existing checkout,
refresh relevant Drive documents and the published website, and independently
check saved evidence. This is a read-only resumption audit followed by planning.
No application code, model, calibration, dataset or existing document was changed.
No commit, push, PR, deployment or clinical message was made.

## Verified workspace and artifacts

- Workspace: `C:/Users/Aditya/SentinelWard`.
- Branch: `phase/2-a1-alerts`; HEAD `81bc5f0832a17efbf7fb6bad05d40c609c189c17`.
- Remote URL matches the handoff. GitHub's current remote state was not fetched.
- Before these two new planning documents, 72 modified/untracked entries were
  present. Existing Phase 2/3 source, tests, migrations and research tools remain.
- No applicable `AGENTS.md` was found in the workspace root or repository search.
- Package `0.3.1`, scorer `m6-research-0.3.1`, Python requirement `>=3.12,<3.13`.
- Available space observed: C: 454,991,872 bytes; D: 102,875,746,304 bytes.
  Keep bulk data, environments and caches on D:. Nothing was deleted or moved.
- All 921 new-cohort receipts independently passed byte-size and SHA-256 checks:
  1,187,600,265 bytes. Screening downloads are included; this is not a count of
  921 patients or selected cases.
- Both original and resumed execution snapshots passed their recorded hashes
  (five source files each). All 40 current Python source modules match the
  isolated installed wheel environment.

| Artifact | Recomputed SHA-256 |
|---|---|
| Selected model | `fcf46ebbc250df079fa1bb84137903a57c15d9df5a3ed037da8c3200e9a5d5ef` |
| Report | `0180bb5ba32cc685748aef0211aa40320dd80f691dc174d46e72a7c168a82a9d` |
| Held-out predictions | `d6209d41c8e4a77229535880ab41df28a985ffb42697addc0bdebd19096c2b66` |
| Handoff wheel | `271fb83e798d66f35828d1b9e7c4895352b8bd86137b56af7a068ebe61286c0e` |

Artifacts remain in the paths specified by the master handoff. Raw waveforms,
patient-level feature files and weights remain outside Git.

## Current status, distinguished from historical checks

| Area | Verified state | Outstanding gate |
|---|---|---|
| Phase 0 | Local contracts/plans/fixtures retained | Team sign-off, access and walkthrough |
| Phase 1 | Engine, typed contracts, persistence, MQTT/backend adapters retained | LinuxONE and authenticated live integration |
| Phase 2 | A1 alert lifecycle and durable timer implementation retained | Actual primary screen, phone backup, live callbacks and restart gate |
| Phase 3 | M6 research runtime, replay/training/evaluation and cold-gap path retained | Coverage, reviewed truth, representative safety evaluation and team acceptance |
| Phases 4–7 | Plans retained | Implemented integrations/features, integrated demonstration and submission handoff |

Parsed saved JUnit evidence records **123 passed, zero failures/errors/skips,
42.150 seconds**, timestamp `2026-10-09T21:17:17.351045+05:30`. This suite was
not rerun during resumption. Receipt checks, source/hash comparisons, prediction
metrics and saved-window counts were recomputed today. Those checks do not
reproduce PostgreSQL integration, installed migrations or live delivery.

The current repository's read-only connectivity audit found:

- Profile `test`; external effects `simulate`; M6 disabled, no context/calibration.
- PostgreSQL unreachable or authentication failed. No server was started.
- MQTT TCP unreachable; TLS remains required; CA and credentials unconfigured.
- Backend and Telegram unconfigured. Authenticated pub/sub, screen delivery,
  phone delivery and LinuxONE remain pending. No clinical messages were sent.

CI currently installs the dev extra, not the research extra, and has no VitalDB
root. A successful default CI run would not establish execution of every optional
research/data check from the fully enabled historical suite.

## Independently recomputed M6 evidence

Saved predictions contain 4,089 usable windows from four independent held-out
patients. Forest MAE is **8.553879 mmHg**, paired old ridge **10.099416 mmHg**;
forest RMSE **11.829277**, bias **-0.068584**, MAPE **11.070453%**. Counts within
5/10/15 mmHg are 1,418/2,895/3,634 respectively. These are monitor-MAP regression
metrics, not drift-classification accuracy or independently measured true BP.

The preserved patient bootstrap interval for MAE improvement is -1.0557 to
3.9398 mmHg. It includes zero; one patient worsened. That uncertainty was read
from the verified audit; it was not recomputed in this resumption.

Streaming the saved original-reference rows from all 12 score files gives:

| Recorded routing reason | Windows |
|---|---:|
| Fresh cuff unavailable | 5,006 |
| Waveform missing/incomplete/unusable | 3,542 |
| Possible deterioration guard | 6,027 |
| Low cuff guard | 1,660 |
| HR/timing unavailable | 72 |
| Baseline collection | 547 |
| Gap-only assessment, both historical reason wordings combined | 414 |
| Total | **17,268** |

Independent availability flags overlap and must not be summed as exclusive
categories: fresh cuff 5,084/17,268 (**29.44%**), extracted pressure features
13,511/17,268 (**78.24%**), urgent patient-review precedence 7,687/17,268
(**44.52%**), sufficient drift inputs 414/17,268 (**2.40%**, all gap-only).
There were zero combined-baseline assessment windows.

Full baseline readiness remains **0/12**, maximum 111 versus 179 required.
Sorted final counts: 0, 0, 1, 6, 14, 43, 48, 70, 76, 89, 89, 111. Of 537
transitions between recorded baseline additions, 70 exceed the five-second hop;
the longest gap is 5,130 seconds (**85.5 minutes**). These counts follow increases
in `extra.baseline_windows` in reference rows; no raw recording was reparsed or
rescored. They confirm collection across gaps, not a consecutive 15-minute rule.

The saved controlled-perturbation coverage is 1.75–3.38%, depending on variant.
Those experiments and low-pressure synthetic controls remain research evidence.
No clinician-reviewed genuine drift/hypotension labels or verified cuff-acquisition
times became available through this source refresh.

## Refreshed Drive and website sources

The [project folder](https://drive.google.com/drive/folders/12SDtIMOuB3DopNXyaQOAbahT-YTlN0kJ)
was listed through the connected Google Drive plugin. Relevant current text was
fetched from locked Doc 00, Aditya v3, R10, R11, R9, the lead and Singhal plans,
the pack README, R8, R12b, team brief and combined research document. Larger
research/screen documents were inspected for relevant sections; this is not a
claim that every Drive file or every historical revision was read. The listing
showed newer Oct 8 metadata for some documents, but no relevant Oct 9 completion
report. Metadata alone does not prove a substantive revision.

The [published website](https://sentinelward-inside.vercel.app/#/ring) was reached
directly via HTTPS, including its current `index-Drb0yDm_.js` content bundle.
M6, engine, A1, Granite, ownership and safety/reference content were inspected.
The web text reader failed on the app; direct fetching succeeded. Browser
interaction and runtime backend operation were not tested. This website explains
architecture and planned work; it is not the verified primary clinical screen.

| Disagreement | Evidence and resolution for this continuation |
|---|---|
| Pre-17-Oct no-code text | Still in [Doc 00](https://docs.google.com/document/d/1WoAMEcL5AiB1jL-2oGDVE682LpEHR1Esi2Y8i0a3oHU/edit) and team plans. The handoff records later user authorization and local implementation; preserve it. Event eligibility was not independently adjudicated. |
| M6 called `P(drift)` | [R10](https://docs.google.com/document/d/1RLk68E3HkTJNIu96u71jEgsEGiFQC7U7NVjZZNQnrPg/edit) uses probability wording. Current M6 explicitly emits an uncalibrated evidence index; do not relabel it a probability. Locked score fields stay unchanged. |
| Phone-before-screen sequence and DRIFTING low priority | [R11](https://docs.google.com/document/d/1SaD60f1lrpUgjKemy3YoNnE98ERCKBKeA2-usyx_JfY/edit) has older wording. [Doc 00](https://docs.google.com/document/d/1WoAMEcL5AiB1jL-2oGDVE682LpEHR1Esi2Y8i0a3oHU/edit) fixes DRIFTING at medium; [Aditya v3](https://docs.google.com/document/d/1p0n_FmMwKdQsRGhz0sn745EgjIDCQUBzHKGbBUMOPYw/edit) and current A1 preserve primary-screen/phone-backup behavior. |
| Baseline described as 15 minutes/900 seconds of coverage | Source and saved additions show 179 eligible overlapping windows accumulated across gaps. Consecutive duration, reference count and elapsed span require separate reporting. Existing documents were not overwritten. |
| Between-cuff prediction and cause certainty | Website describes these as capabilities. Current combined path still requires fresh cuff evidence; no baseline became ready. M3/M5 hints do not prove malicious intent. |
| Old research owner/verdict wording | Combined research section 5.9 still assigns M6 to Singhal and folds drift into loose sensor. Later locked Doc 00 and owner plans establish Aditya ownership and canonical DRIFTING. |
| Framework choice and name spelling | Team sources still offer LangGraph/BeeAI alternatives and spell the screen teammate Antara Gupta. Local choice is LangGraph; no wire IDs or local names were changed. |

No Drive or website document was edited. Continue with the
[M6 improvement plan](m6-improvement-plan-2026-10-09.md).
