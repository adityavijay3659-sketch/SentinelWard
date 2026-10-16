# Phase 5 implementation verification — 16 October 2026

Local A5/A7/A8 implementation and recovery are complete on `phase/5-narrative-agents`, based on Phase 4 `e01e090`. Changes remain uncommitted/unpushed. **Core workflows are ready in template mode; strict local Granite generation acceptance is closed.** The final bounded local contention comparison passed; this does not close full-system or target-host acceptance. The example/default remains `writer=null`. Backend/screens/LinuxONE and the live whole-team demo remain external Phase 6 gates.

## What changed

- A5 supports authenticated confirmation, independent notice/observation/confirmation times, anchored six-hour clock, missing fields/provenance, edit/review/PDF and exact-revision human partial-send attestation. No automatic sender.
- A7 counts distinct screen-routed alert/recipient facts, including a new escalation recipient once, in the exact two-hour interval; warns strictly above 40 without reassignment.
- A8 provides causal full fact snapshots, current urgent state independent of prose, explicit unavailable/coverage/suppression provenance, on-demand/shift/T+19 scheduling and offline exclusions.
- Recovery adds bounded stage diagnostics, compact complete composition, versioned cache identity, cancelled obsolete inference, preserved PDF/revision on failure and bounded native coverage rows. Human work, clocks, audit, run isolation and MQTT envelopes are preserved.

## Established causes and repair

The frozen original five-fact report was reproduced with IDs `[f4,f0,f1,f2,f4]`: duplicate f4 and missing f3. The verifier correctly rejected it after 74.80 seconds. The original fifteen-fact briefing timed out at 120.06 seconds. These are measured reproductions, separate from the historical 68.05/120.00-second failures.

Pinned-tokenizer canonical output sizes for 5/15/30/42 facts were 68/203/413/581 tokens. The old 42-fact representation exceeded the unchanged 512-token cap. Compact canonical output is 18/28/43/55 tokens; pre-stream compact requests were 1,247–1,288 bytes, well below the unchanged 24 KB bound. SSE changes transport options, not the model prompt or output representation. The model selects only source/reverse ordering and one reviewed wording bit per fact. Code supplies every ID/predicate/value and independently verifies the complete native v1 composition. No facts are removed. Prompt/cache identity is `phase5-3`; model-only wire is v2; phrase definitions remain `phase5-1`.

The intermediate `phase5-2` comparison accepted 19/20 but missed the scheduled 12-bed deadline at 45.12 seconds; retained as failed evidence. Removing redundant IDs and variable system-prefix data produced a 20/20 pre-stream result. That earlier run was interrupted between cases overnight and resumed after validating the saved prefix. After the real cancellation audit exposed continued server computation, the transport was repaired and the entire 20-case matrix and unchanged 30 cases were repeated, rather than treating pre-stream acceptance as final evidence.

## Actual local Granite acceptance

Same Granite 3.3 2B Q3_K_S artifact, SHA-256 `ca71c0faaea5647c6f34bb55d8ae9516e94828e0065cdbbf4680348be2bbbfd3`; llama.cpp build 11433/`50569eb87`, two threads, one slot, context 4096, max output 512, fixed seed/temperature, no tools/thinking. Ordinary total deadline remains 120 seconds; scheduled remains 45 seconds. No training or model swap.

| Gate | Accepted / required | Median / p95 |
| --- | --- | --- |
| Original unchanged small fixtures | 30 / 30 | 10.25 s / 16.66 s |
| Six full coordinator workflows ×3 plus two scheduled cases | 20 / 20 | 23.22 s / 38.31 s |
| Additional cold-process, 12-bed scheduled case | 1 / 1 | 38.09 s; only 6.91 s budget margin |

The full fixtures include complete/incomplete A5, normal/urgent 3-bed A8, 8-bed A8 and urgent 12-bed A8 (5/15/30/42 facts). Fallback fails the strict acceptance command; intentional resilience fallback is tested separately. All accepted facts remain traceable and urgently flagged state stays code-owned. These finite fictional software cases are neither free-form language validation nor a clinical/reliability claim.

## Productivity, cancellation and load limits

Failed generation leaves document/PDF/review unchanged and records outcome in durable job/audit. Reference report/briefing responses expose top-level `generation`; backend/UI must consume it rather than interpreting the immutable initial template's pending reason as live status. Accepted material refinement still advances revision and invalidates the old export/approval. Disabled writer emits one labelled template and no job. Reset, human edit and authorized undo retire/cancel obsolete work; software tests prove they do not wait on inference under lifecycle locks.

The original 10-second server-idle assertion failed. A second non-streaming audit found that the Python job retired in 31 ms but the server continued to normal completion for about 34 seconds. Eventual idle was not counted as successful server cancellation. The adapter now requests bounded SSE and consumes it without publishing unfinished output. Missing stop/DONE, invalid fragments, reasoning/tools and duplicate keys remain rejected.

The final actual owned-server probe reports client/job cancellation in 0.015 seconds and server slot release within 6.469 seconds of reset, with **an actual server cancel log**, not merely a normal completion. A first streaming probe also logged cancellation and released in 0.968 seconds. The observation harness allows a nominal 30-second diagnostic polling interval; runtime deadlines remain 45/120 seconds. Cancellation is cooperative, not a hard real-time CPU guarantee.

Native coverage coalescing reduced a 120-tick/12-bed trace from 1,428 rows to 12; final-ten-tick median fell from 57.50 to 3.32 ms. Separate tests preserve exact duration and do not bridge expired trust gaps or mutate external receipt semantics.

Three alternating template/model pairs replayed 1,200 logical seconds and 12 beds, with actual concurrent 42-fact Granite. Offline timing, urgent state, typed output and reset/new-run checks passed. This is accelerated local lifecycle/ledger load, **excluding raw vitals, MQTT, M6, real backend/UI and full-team timing**.

| Host profile | Template median p95 | Model median p95 | Relative change | Predeclared ≤10% gate |
| --- | --- | --- | --- | --- |
| Pre-stream unrestricted 2-core/4-thread laptop | 33.42 ms | 43.08 ms | +28.91% | FAILED |
| Disjoint CPU masks: coordinator 3, model 12; restored afterward | 21.27 ms | 50.94 ms | +139.42% | FAILED |
| Final SSE transport, original unrestricted profile | 62.51 ms | 68.02 ms | +8.82% | PASSED |

CPU isolation did not establish a successful profile. The final original-profile comparison was repeated because streaming changed the transport; all earlier results remain preserved. No threshold or performance gate was relaxed. The final bounded local contention comparison passed; this does not close full-system or target-host acceptance. Three pairs are limited engineering evidence, not a reliable estimate of deployed latency or proof that SSE alone caused any timing change. Target-host resource isolation/capacity must pass before deployed simultaneous model operation; LinuxONE cannot be assumed to pass. The plan's full live ingress/alert/DB/outbox/CPU/memory acceptance remains Phase 6.

## Final verification

- Full pytest: **229 passed, 0 failed, 0 skipped**, 198.66 seconds. JUnit XML is authoritative; focused suites are not added to this total.
- Python 3.12 development interpreter; real isolated PostgreSQL and MQTT, actual local Granite and unchanged existing VitalDB tests enabled. Additive migrations 0001 through 0007 and checkpointer initialization passed in a new dedicated DB. Restart/lease/history/reset tests passed.
- Ruff lint and formatting passed; strict mypy passed for 59 source files. Twenty focused recovery cases passed, including duplicate/schema/truncation, complete/rejected SSE, 64-fact expansion, exact PDF preservation, disabled mode, reset/edit/undo cancellation, queue-eight/overflow/expiry and coverage continuity. The combined focused Phase 5 suite passed 42 cases before the final full run; these are not added to its total.
- Wheel built, reinstalled in a separate Python 3.12.14 environment and imported from installed site-packages outside the checkout. Packaged migration 0007 is present. Actual CLI startup passed: live health 200, internal unauthenticated 401/authenticated 200, nurse briefing read 200. The owned child stopped afterward.
- Changed-file credential/link/hash audit is recorded separately in the private evidence directory. No actual UI acceptance or external send is claimed.

The first post-stream cold replay lost its evidence write to `errno 28` (C: full), and the command sequence stopped before the full suite. It is retained as incomplete environmental evidence, not an accepted generation. After user-authorized cleanup, the same fixed cold case was rerun in a fresh process and the full suite used D: scratch. Cleanup removed 148,260,788 logical bytes of our disposable caches, old pytest folders and completed wheel-verification environment; source, datasets, models, credentials and audit evidence were retained. C: free-space changes beyond that amount are not attributed to this cleanup.

## Frozen sources and ownership

Production `m6.py` SHA-256 `4b1c9084935a8d253fd00d67f9011c464281d79928cbd9a2f4d7c90d2b66c4c7` and isolated C1 SHA-256 `ede527738073fb8774406773da4970a8d9ee034caf78fe185f5d2351ecafad9f` match the frozen values. No M6 scoring/baseline/threshold/guard/model change, retraining, calibration, patient replacement, C1 merge, new M6 experiment, push, merge or deployment occurred.

| Remaining item | Owner / status |
| --- | --- |
| Staff sessions/grants, real roster/profile, public API/WS, run/revision rejection, generation job status projection | Backend dependency |
| S8/S10 edit/checklist/partial-send/missing/urgent/provenance displays | Antara / screen owner |
| Actual scoped A3 evidence/artifacts | Kartik dependency |
| Authoritative coverage/suppression receipts and definitions | Backend / decision owner |
| Simulator/attack reset, current-run identity and source completion | Simulator dependency |
| TLS/ACLs, one service leader, verified LinuxONE artifact/resources and comparative model load | Broker/deployment dependency; NOT accepted by local generation success |
| Separate human mark-sent MQTT action versus locked agent-only action.by | Contract ambiguity; current typed record/audit attestation is safe and documented |
| Full live 20-minute connected demo | Phase 6 whole-team acceptance |

Evidence: `C:\Users\Aditya\SentinelWard-Phase5-Recovery-20261015`; original failures/evidence remain in `C:\Users\Aditya\SentinelWard-Phase5-Lab`. Raw fictional responses, model files, private profiles, broker logs, built package and DB audit stay outside Git. See [sanitized evaluation](phase-5-evaluation.json), [contracts](phase-5-contracts.md), [runbook](phase-5-runbook.md), [checklist](phase-5-checklist.md) and [recovery plan](phase-5-granite-recovery-plan.md).
