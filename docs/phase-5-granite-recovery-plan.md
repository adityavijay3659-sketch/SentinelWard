# Granite full-workflow recovery and acceptance plan

Status: **LOCAL CODE AND GENERATION RECOVERY ACCEPTED; DEPLOYMENT GATES OPEN — 16 October 2026**. The user authorized this plan's implementation. Current outcomes are in [verification](phase-5-verification.md) and [evaluation evidence](phase-5-evaluation.json). Final streaming full-workflow generation passed 20/20; the unchanged small fixture passed 30/30. The final bounded local contention comparison passed the unchanged 10% gate at +8.82%; earlier unrestricted/CPU-isolated failures remain preserved. These variable local measurements do not certify the full target-host workload. Default/rollback remains template mode; deployed model enablement requires Phase 6 resource/integration acceptance. Production M6 and C1 remain frozen. No push, merge, deployment, retraining or teammate-system changes.

The following sections preserve the original pre-implementation diagnosis, gates and proposed work, rather than rewriting them as if the outcomes had been known. G1 reproduction subsequently proved duplicate/missing IDs in the original report, and G2 measured an over-budget 42-fact serialization. The implemented model-only compact selection preserves all native facts and the independent verifier. G6's bounded local lifecycle/ledger contention check is explicitly narrower than live vitals/alert/DB/broker/UI load; those full-system measurements and G7 deployed enablement remain Phase 6/owner acceptance.

## Outcome and effect on productivity

Enable optional Granite refinement only when real report/briefing workflows generate verified results within their declared budgets, without delaying alerts, invalidating human work or misrepresenting fallback as model success.

Current templates permit report drafting, editing, PDF export, human submission attestation and briefings to continue. Granite is not the authority for numbers, action execution, clinical interpretation, M6 scoring or urgent-state display. Its current failure does not itself mean these functions are broken. It also does not prove that deployed operation is free of integration or resource-contention errors.

| Risk if unaccepted generation is enabled | Evidence/status | Containment / required proof |
| --- | --- | --- |
| Waiting for prose that never completes | Full briefing timed out at 120 s | Immediate template; total deadline including queue wait; expired job terminal; no automatic retry loop. |
| Rejected output and reduced narrative benefit | Full report rejected at 68.047 s | Keep verifier; diagnose exact rejection; measure accepted generation separately from fallback. |
| CPU/memory contention affecting other work | Model working set sampled near 1.86 GB; live multi-bed latency not benchmarked | Template-only operational profile until comparative load test passes. Separate inference resources/capacity only if measurements justify it. |
| Growing queue / jobs expiring before service | One worker, queue eight; queue-load acceptance not yet demonstrated | Test queue ages, admission, deadlines and overflow under simultaneous requests; preserve immediate templates. |
| Re-export work after a failed optional refinement | Current failure path increments report revision and clears PDF metadata even when rendered template text is unchanged | Reproduce this case; distinguish job status from document change; preserve human/sent protections and exact-document audit. |
| Backend/UI calls a fallback “Granite generated” or “ready” | Real deployed views are external and unverified | Distinguish software availability, generation outcome and model acceptance in typed data/UI. |
| Future failure cannot be diagnosed efficiently | Current journal retains broad exception class | Add bounded stage-specific diagnostics, without secrets/PHI. |

## Verified facts and unknowns

- Frozen local Granite artifact/build: 3.3 2B Q3_K_S, llama.cpp 11433 / `50569eb87`; exact hashes are in verification.
- Thirty predeclared small fictional cases passed. This is not larger workflow acceptance.
- The actual report snapshot had **5 facts**; the actual three-bed briefing had **15 facts**. Final outputs were template fallbacks, with `ValueError` and `TimeoutError` respectively.
- Existing test `test_actual_granite_report_and_briefing_workflows` checks safe success/fallback handling. It does not require actual Granite success. Keep that test; create a separate strict acceptance gate.
- The current array grammar constrains individual ID/predicate pairs and sentence count, but does not guarantee each ID appears once. Repeated valid IDs can satisfy that grammar; the independent verifier rejects them. This is a design gap, **not a proven diagnosis of the saved report rejection**.
- Several failures collapse to `ValueError`: prompt bound, truncated response, unexpected output, JSON/schema validation and fact-binding checks. The exact saved rejection cannot be inferred from that class alone.
- The 512-token output budget and 24 KB request bound must be checked against the complete expected fact inventory. With current fact construction, eight beds produce 30 briefing facts and twelve beds produce 42; verify those numbers against the frozen fixtures before measuring.
- A previous timeout completed late; a later run timed out at 120 s. The commit-time deadline guard already rejects late success. Scheduling versus cancellation versus resource contention has not been quantitatively isolated.

## Fixed constraints

Preserve factual validation, complete structured source facts, missing/unavailable qualifiers, urgent sections, human review/approval, no automatic sending, run/revision isolation, audit and reset semantics. No M6/C1 changes. No model training, model/artifact switch or new external provider in this plan. Keep 45-second scheduled-demo and 120-second ordinary total deadlines, one worker and queue eight for the first comparison. Raising limits is not the first repair.

Model output remains controlled composition, never executable tools/free-form authority. No patient notes, contact details, raw signals or secrets enter prompts. Any internal composition schema change receives a version and invalidates incompatible cache entries without rewriting historical records. Locked MQTT envelopes remain unchanged.

## Ordered work packages and gates

### G0 — Preserve usable operation and freeze evidence

Use the existing `writer=null` operational profile until acceptance passes. Do not silently rewrite a private running profile. Record whether a target instance is template-only or model-enabled; switching a deployed instance remains owner-controlled.

Preserve original 30-case results, both full-workflow failures, snapshots, artifact/build identity and source hashes. Establish template-only baseline behavior on the exact target workload. Keep the existing approved Phase 5 core implementation independently reviewable.

**Done when:** baseline evidence is immutable, no model dependency blocks documents/alerts, and users can see the actual generator and missing data. Owner: Aditya locally; backend/screens for deployed display.

### G1 — Add diagnostic detail and reproduce the original failures

Change only diagnostic code first:

- In `adapters/granite.py`, distinguish `request_too_large`, `transport_error`, `response_too_large`, `response_truncated`, `unexpected_tools_or_reasoning`, `invalid_json` and `schema_invalid`.
- In `phase5_facts.py`, distinguish unknown/duplicate/missing fact ID and predicate mismatch. Do not weaken any rejection.
- In `phase5.py`, journal error code/stage, snapshot/model/schema identity, fact count, response finish reason/token usage where supplied, queue wait, inference, validation and commit durations. Preserve original errors as historical evidence.
- Store capped raw model responses only in the isolated protected diagnostic directory, with retention and credential/PHI checks; normal audit must use codes/hashes rather than arbitrary exception dumps. Capture the request's nonsecret configuration and the compiled grammar/capability evidence.
- Use real clocks for performance acceptance. Keep controlled clocks for deterministic lifecycle tests; do not use them to infer end-to-end latency.

Replay the exact failing five-fact report and fifteen-fact briefing before changing prompts/schema/runtime parameters. Record complete raw output/finish reason or the exact stage reached at timeout. If the original rejection is intermittent, retain every attempt rather than selecting a successful response.

**Done when:** the report failure has an identified rejection stage with reproducible evidence, and briefing time is decomposed into queue, processing and cancellation. If not, improve diagnostics; do not guess a model-quality or hardware diagnosis.

### G2 — Prove the request can fit before inference

Use the pinned model tokenizer and deployed grammar converter/capability probe. Count actual prompt/schema bytes, prompt tokens and tokens for a canonical valid composition for 5, 15, 30 and 42 facts, including JSON syntax. Measure cold/warm overhead and observed generation throughput. Test exact grammar features on build 11433; current upstream documentation alone is not proof of that binary's behavior.

If the minimum valid result cannot fit 512 tokens or measured throughput cannot plausibly complete within its total deadline, record the incompatibility before launching a doomed job. Do not hide omitted facts or call the incompatible case accepted.

**Done when:** each required workflow has a measured feasible envelope, or a clearly recorded capacity/representation blocker. This gate determines whether code repair or deployment resources are the next dependency.

### G3 — Apply the smallest evidenced correction

Choose a change only after G1/G2 identify its trigger:

| Established cause | Authorized repair direction for a later implementation |
| --- | --- |
| Duplicate/omitted IDs despite syntactically valid output | Strengthen decoder representation to require every declared fact structurally; retain independent coverage verification. Probe a compact keyed representation with all IDs required and additional keys forbidden. Preserve validated ordering/wording semantics and explicitly version any changed internal format. |
| Redundant JSON makes output infeasible | Derive redundant predicates from trusted facts and test a compact representation, preserving every required fact and its independent binding checks. Keep source snapshots/structured appendix complete. |
| Incompatible/unsupported grammar | Repair the schema/converter usage on the pinned build and test compiled grammar with valid/invalid examples. Do not rely on unsupported uniqueness keywords. |
| Truncated output | First remove measured serialization overhead. Recheck the fixed token/time envelope. Do not automatically increase max_tokens/context/timeouts. |
| Adequate format but insufficient throughput | Measure the same model/contract on the intended LinuxONE runtime with its verified artifact/byte order. Keep local template mode; resource acceptance is a deployment dependency, not a claim that hardware will fix correctness. |
| Transport, cancellation or expired-queue failure | Fix the observed layer with bounded I/O/cancellation and expired-job handling; no unbounded retries or extra concurrent workers. |

One change per comparison; preserve the original failure fixtures and report both accepted and rejected attempts. Do not replace full workflows with only easy small inputs. If a representation change changes approved narrative semantics, obtain that scoped decision before implementation.

**Done when:** the original failure no longer reproduces in the declared repetitions, valid full results fit the original budget, and the verifier's adversarial rejection tests remain healthy. If this is infeasible under fixed constraints, stop the repair loop and keep optional Granite disabled pending a documented resource/scope decision.

### G4 — Eliminate avoidable workflow and queue disruption

Reproduce PDF export during pending generation, then invalid/timeout completion. A failure that leaves rendered content unchanged should not force a new export just to record job status. Keep job outcome/audit visible; accepted material document changes must still create a revision and invalidate its prior export/approval. Human edits, reviewed/sent artifacts and new-run state must always win.

When the writer is explicitly disabled, plan to emit the labelled template directly without enqueueing inference that cannot run. This is a proposed Phase 5 efficiency correction, not a claim about existing disabled-writer behavior.

Exercise queue capacity 8 and overflow request 9, a waiting job whose deadline expires, unavailable server, reset during generation, duplicate delivery, restart lease recovery and source changes. Verify that the server stops work after cancellation rather than continuing to consume resources for retired jobs; use only owned test processes for any recovery action.

**Done when:** no lost human work, no revision/export changes caused solely by an unchanged failed refinement, no duplicate publication, no stale-run result, no retained inference for cancelled owned jobs, and immediate templates remain available under every injected failure.

### G5 — Run a distinct strict Granite acceptance suite

Keep three clearly named result groups:

1. Existing small real-model benchmark: all 30 original cases, unchanged.
2. Software resilience tests: intentional model failure may pass only by producing correct fallback and preserving invariants.
3. **Strict generation acceptance:** fallback, retirement, rejection or lateness does not count as model success.

Predeclare six complete generation fixtures before evaluating the repair: complete A5 report; incomplete A5 report; three-bed normal A8; three-bed urgent A8; eight-bed A8; twelve-bed A8. Retain all relevant current/unavailable/urgent facts. Repeat each three times (18 required full generations), including declared cold/warm runs. Add separate scheduled-demo deadline cases. Actual LinuxONE uses the same logical cases with its separately verified artifact.

Proposed engineering acceptance gate, to be fixed before running:

- All 18 ordinary required full generations accepted within 120 seconds total, including queue wait; required scheduled-demo generations accepted within 45 seconds if advertised as Granite-supported.
- Zero accepted missing, duplicated, invented, misbound or wrongly qualified facts. Required urgency and incomplete-reference information remain visible independently of prose.
- Zero stale/human-overwrite/unauthorized send outcomes; correct fallback in every intentional failure case.
- No cherry-picking cases, extra retries, hidden timing exclusions or verifier relaxation to achieve the target.

These are limited software acceptance requirements, not reliability estimates or clinical validation. If scheduled-demo Granite cannot pass, label that use template-only; do not claim demo Granite acceptance. Any reduction of required advertised workload must be explicitly approved, never silently substituted for these tests.

**Done when:** a dedicated acceptance command exits unsuccessfully on any failed required generation and a report shows real acceptance/fallback/latency per complete workflow. A green general pytest suite alone cannot close this gate.

### G6 — Verify productivity under the actual demo load

Compare template-only and model-enabled operation using the same deterministic 20-minute scenario, simulator cadence, source completion events and 8–12-bed inventory. Do not alter physiological data or M6 to improve results.

Measure ingress backlog/loss/duplicates, alert and ACK latency, lifecycle/reset latency, event-loop delay, DB/outbox delay, generation queue age, CPU/memory and document availability. Preserve urgent precedence and OFFLINE semantics. Test simultaneous report/briefing requests, cancellation and broker/database recovery.

Predeclared proposed performance gate: no dropped/cross-run/duplicate state transitions; no urgent downgrade; all existing absolute project timing requirements met; model-enabled p95 ingress/alert handling no more than 10% slower than the measured template-only baseline. If a metric lacks an agreed absolute SLA, mark that deployment acceptance item open rather than inventing a pass. The relative 10% gate is an engineering proposal, not a pre-existing clinical SLA.

If contention fails this gate, limit/isolate the inference resources on the actual deployment target and rerun the same comparison. Do not assume moving HTTP inference out of a lifecycle lock proves host-level isolation.

**Done when:** actual resource measurements support the intended workload and the team captures backend/API/WS/UI evidence. Owner: Aditya for local harness, backend/simulator/Antara/LinuxONE owners for their actual systems.

### G7 — Enable deliberately, preserve rollback

Enable only the workflows/hardware profile that passed. Record model/build/hash, composition/verifier versions and accepted workload envelope. Start with an explicitly scoped internal demo before wider use. Keep one active service leader, protected profiles, current-run filtering and visible fallback counts/latency/error codes.

If acceptance or operational invariants fail, disable optional generation and continue templates through the already supported configuration. Preserve jobs, documents and audit; never reset M6 or reporting clocks to repair Granite. No automatic retry storm, automatic report send or hidden replacement of human work.

**Done when:** team-owned integration checks pass, rollback is exercised, and the updated checklist separately marks core software, actual Granite generation and deployment acceptance.

## Planned change surface and outputs

- Diagnostic/repair: `adapters/granite.py`, `phase5_facts.py`, narrowly scoped generation handling in `phase5.py`; `phase5_contracts.py` only if the internal composition version must change.
- Acceptance: retain `tests/test_phase5_granite.py` for resilience; add a distinct strict acceptance test/runner and full-workflow fixture file. Extend evaluator for per-stage/capacity metrics without rewriting previous results.
- Persistence: prefer existing job/audit JSON fields; add a migration only if an actual indexed/typed storage requirement appears. Do not delete/rewrite history.
- Evidence: planned private rejection diagnostics, capacity table, original-versus-candidate results, strict acceptance matrix and template-versus-Granite load comparison. Publish only sanitized summary/verification documents.
- Regression: full pytest, Ruff, formatting, strict mypy, real PostgreSQL/MQTT restart/reset, package/CLI checks, and unchanged M6/C1 hashes. Current baseline is 209 passing tests; future counts must come from the actual new run.

## Definition of done

The exact failures are explained; the evidenced fix passes unchanged original and complete-workflow cases; every advertised workflow fits its existing deadline; unsafe output and stale results remain rejected; human work is protected; comparative load does not harm operational processing; intended deployment owners validate their systems. Until then, template mode supports ongoing core integration, while Granite acceptance remains visibly open.

## Technical references checked for this plan

- [Python 3.12 asyncio wait_for](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.wait_for): cancellation completion can extend total wait beyond the nominal timeout. This supports measuring cancellation separately and retaining commit-time deadline checks; it does not diagnose the prior overshoot's exact cause.
- [Official llama.cpp grammar documentation](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md): describes a supported JSON Schema subset, unsupported constraints and possible grammar performance problems. This is current upstream guidance; support/performance must be probed against the project's pinned binary before adopting any schema repair.
