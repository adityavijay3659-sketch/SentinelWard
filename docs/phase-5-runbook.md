# Phase 5 isolated runbook and team handoff

Use [contracts](phase-5-contracts.md), [verification](phase-5-verification.md) and the [final plan](phase-5-plan.md) together. This branch adds A5/A7/A8 locally. Production M6 and isolated C1 remain frozen. No automatic report sender or nurse reassignment exists.

## Setup

1. Use Python 3.12. `uv sync --frozen --extra dev`; apply `uv run sentinelward db upgrade` and `uv run sentinelward db init-checkpointer` to an authorized local database. Migrations 0006/0007 retain per-run records and historical audit. Application rollback never deletes report attestations.
2. Start the existing isolated Phase 4 broker/profile using its [runbook](phase-4-runbook.md). Configure the test-owned inventory and contexts; never point containment tests at shared production accounts.
3. Copy [phase5-config.example.json](../fixtures/phase5-config.example.json) to a private directory outside Git. Supply a versioned roster, charge nurse, expiry, shift timezone/boundaries and declared report profile. Unknown identity/contact/device fields stay missing. Set server-bound staff credentials privately if using the reference API. Empty credentials deny staff access.
4. Set `SENTINEL_PHASE5_CONFIG_FILE` alongside `SENTINEL_PHASE4_CONFIG_FILE`, enabled demo lifecycle/M6 contexts and `SENTINEL_BACKEND_SERVICE_TOKEN`. The factory is deliberately isolated/test-only and HTTP binds loopback. This is not approval for hospital operation.
5. Keep `writer=null` as the default and rollback profile. The pinned local model passed full-workflow generation and the final limited lifecycle/ledger contention gate. Earlier unrestricted/CPU-isolated comparisons failed; timing varied substantially. Use model-enabled profiles only explicitly within the verified isolated lab scope until the real target passes full ingress/resource acceptance. LinuxONE and deployed acceptance require their own measurements. Templates never claim model generation.

An optional private writer profile has `base_url,model,model_file,model_sha256,build,api_key`. Only loopback HTTP is accepted, with no redirects/proxy inheritance, bounded request/response and no tools. Verify the local GGUF hash; do not copy credentials or model assets into this repository. The approved local harness checks the existing Granite 3.3 2B Q3_K_S artifact and launches only the explicitly supplied llama-server binary:

```powershell
uv run python tools/phase5_lab.py start --root <private-lab> --binary <llama-server.exe> --model <approved.gguf>
uv run python tools/phase5_evaluate.py --config <private-lab>/runtime.json --output <new-evidence-directory>
uv run python -m tools.phase5_acceptance --config <private-lab>/runtime.json --output <new-full-workflow-directory>
uv run python -m tools.phase5_load --config <private-lab>/runtime.json --output <new-local-load.json>
uv run python tools/phase5_lab.py stop --root <private-lab>
```

Evaluation uses the committed 30-case fixture. `--resume` verifies saved case order, snapshot hash, model identity and accepted text bindings before continuing; it does not overwrite a different experiment. Preserve unsuccessful attempts too. Cases are fictional engineering fixtures, not clinical evaluation. The full workflow test is separate and must not be replaced by these smaller cases.

The strict source-checkout command uses six full coordinator fixtures repeated three times plus two scheduled cases. Any required fallback, rejection or lateness fails its exit status. The load command compares three template/model pairs of accelerated 20-minute, 12-bed lifecycle/ledger traces with actual concurrent Granite. It excludes raw vitals/MQTT/M6/UI and does not close Phase 6's live ingress or whole-team acceptance gate. Use fresh output directories and one inference consumer at a time for timing measurements.

Keep sufficient scratch space. The final resumed verification sets `TEMP`/`TMP`, pytest `--basetemp`/`cache_dir`, and lint/type-check caches to a dedicated D: verification directory. Use a fresh pytest basetemp path: pytest may clear that directory. Do not point it at datasets, audit evidence, a model directory or an existing user folder. Preserve failed/incomplete result directories; a disk-full evidence write is not successful generation acceptance.

## Start and inspect

Run `uv run sentinelward validate-config`, then `uv run sentinelward serve`. Internal Phase 5 status requires the backend bearer. Reference staff routes require a server-bound staff token; the service bearer alone cannot act as IT on those routes. Keep role/session checking in the real backend.

For a repeatable actual-service startup check, after all database-writing tests finish:

```powershell
uv run python tools/phase5_smoke.py --root <private-smoke-dir> --phase4 <private-phase4.json> --phase5 <private-phase5.json> --database <isolated-postgres-url>
```

This validates configuration, starts the real CLI on loopback port 18095, probes authenticated/unauthenticated internal and nurse routes, writes evidence outside Git and stops its own child. It does not call external systems or claim UI acceptance. Use a dedicated test DB and unused port. Service health can honestly show an absent external backend/Telegram; a startup check is not a whole-system readiness check.

## A5 human workflow

1. IT reviews a current-run A3 incident. Backend registers a grant bound to IT, request/run/action/target/expiry, then confirms the report. Provide notice time and reason when known. Without that review, first machine observation is an explicitly provisional anchor; confirmation does not restart six hours.
2. Initial template is available immediately. Check every missing field and evidence availability; actual action failure/unknown is preserved. Optional background refinement must pass the verifier and current-run/revision check.
3. Apply edits with expected revision. Human prose is labelled human/unverified; material edits clear approval and export identity. A separate review sets facts_checked/evidence_reviewed/approved for the resulting revision.
4. Export PDF. It contains draft/demo and missing-field markers, source hashes and revision; return its exact document hash. Download is possible while incomplete. PDF export never sends.
5. A person sends through their approved channel outside this service. IT may attest using the reviewed revision/hash/send time. For partial information, explicitly acknowledge all missing fields and follow-up note. This records an attestation with receipt_verified=false, not a verified CERT-In receipt or legal compliance.
6. Sent/human-edited revisions cannot be undone or overwritten. An unsent generated artifact can be superseded through its owner; its reporting clock and history remain. `start_clock` has no undo capability.

The pinned primary-source legal note is informational and requires human applicability/currentness review. It does not decide whether a hospital must file or guarantee acceptance of the draft layout.

## A7 and A8 operation

A7 runs once per minute, counts distinct screen-routed A1 alerts per nurse over two hours, and warns strictly above 40. A different escalation nurse is a new recipient, not a duplicate. Phone retries and acknowledgements are excluded. Missing roster/charge nurse is explicit; no automatic reassignment occurs.

A8 can be requested by nurse/doctor, scheduled at configured timezone shift boundaries, or at demo T+19:00. It publishes structured facts, current urgent state and a template first. Ordinary refinement has 120 seconds total from queueing; scheduled demo has 45 seconds and is also bounded by demo end. Queue size is eight with one worker; overflow/invalid/truncated/unavailable/expired jobs keep a labelled template. LinuxONE budgets must be measured independently.

Read Blind Time alongside unknown coverage and outside-recording duration. Known completion is offline, excluded from the recording metric; it creates no model alarm. Missing suppression evidence is unavailable, not zero false alarms prevented. Briefing urgent state is independent of generated prose and refreshed from durable A1 state.

## Reset, recovery and troubleshooting

Reset retires pending/running jobs and pending/failed run outbox entries; it preserves records, notice clocks, human attestations, source receipts and audit. A new run uses a fresh namespace, including repeated bed cursor keys. Completed historical sends cannot be rolled back by reset. In-flight old-run MQTT records still require backend rejection.

Generation leases permit restart recovery. Inference runs outside transactions/lifecycle locks; late results lose to reset, superseded targets, sent revisions and human edits. Failed schema/predicate/coverage checks select templates; do not relax the verifier to improve the success count. No inference callback can execute an action.

Inspect `/internal/v1/phase5/status` jobs for accepted/fallback/retired, reason, elapsed time, snapshot and model identity. Inspect audit/outbox for persistence/delivery failures. Do not run multiple scheduler/worker service leaders against this isolated runtime; the supported topology is one active leader with durable recovery.

The latest reference report/briefing response has a separate `generation` field with current job state/reason. Failed refinement preserves document revision and exact PDF; inspect that field or the internal jobs rather than treating the initial template's `generation_pending` reason as live status. Job diagnostics retain safe stage codes/hashes/token usage/timing, not raw responses or credentials. Accepted refinement creates a new document revision; human-edited/sent work always wins. Model-only protocol `phase5-3` invalidates incompatible caches without rewriting historical documents.

## Deterministic team smoke test

| Step | Required evidence |
| --- | --- |
| RESET → RUN | Trusted control MQTT; distinct run/episode IDs; current lifecycle DB rows; old jobs retired, history retained. |
| Simulator sends current vitals | Original vitals topic/payload; M6 score contains extra.demo_run_id; last values appear through real backend/UI. No fabricated unavailable score. |
| Urgent/BOTH scenario | A1 screen alert remains active despite containment. Request ACK/escalation uses A1 with actor; current urgent section remains independent of Granite. |
| IT confirms report | Authenticated actor/grant; one A5 draft and original notice deadline; typed ward/record; missing fields shown in S8. |
| Edit/review/PDF | Stale edit rejected; new revision clears approval; PDF hash and revision match exact export. Wrong role denied. Human send attestation does not send anything. |
| Workload boundary | 40 unique addressed alerts → no warning; 41 → one charge-nurse warning. Retry/ack/phone backup → unchanged count. Show routing versus delivery. |
| Briefing | Nurse/doctor Generate now and T+19 produce current-run fact snapshot; unavailable suppression/coverage shown. Template provenance survives model outage/timeout. |
| Short source completes | Explicit endpoint or known timer; OFFLINE + offline_since + last readings in real API/WS/UI. No M6 alert created from silence. |
| Delayed output | Hold old-run score and A5/A7/A8 record; reset/new run; deliver old messages. Backend rejects extra.demo_run_id or data.run_id before current projection. |
| RESET → second RUN | No inherited model baseline, alert timers, workload, trust cursor, job or agent active scope. Historical DB/audit and sent records remain. |
| Deployment gate | Capture real API/WS/UI/log/DB/MQTT evidence, deployed ACLs, source semantics and LinuxONE actual report/briefing acceptance. Local tests alone cannot close this gate. |

Backend/Antara/Kartik/decision/model owners must complete their own rows in the [contracts](phase-5-contracts.md). No teammate systems were changed or automatically notified.
