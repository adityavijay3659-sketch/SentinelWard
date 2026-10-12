# Phase 4 local implementation and verification

Status: **LOCAL_VERIFIED** on `phase/4-agent-integration`, based on published checkpoint `905235d`. At the verification checkpoint these changes were uncommitted; subsequent publication is recorded in Git history. No merge or deployment was performed. This report closes the revised local implementation gate agreed with Aditya; team deployment acceptance remains separate.

## Delivered behavior

| Capability | Implementation and observable evidence |
| --- | --- |
| Routing | Optional Phase 4 LangGraph node handles all eight canonical verdicts. A1 runs independently before containment/evidence/ticket work. Failed security effects cannot suppress BOTH's urgent response. |
| A2 | Real Mosquitto Dynamic Security disable/enable; independently journalled session cleanup and untrusted projection. Inventory binds device, bed, username and client ID. |
| Authorization/undo | Trusted backend registration validates identity, IT role, scope, target and expiry. Undo resolves A2/A4/A6 ownership, preserves audit and links compensation to the original action. An older containment undo cannot enable a device isolated by a newer action. |
| Recovery | Pending intent is committed before external work. Ambiguous replies remain unknown and reconcile on retry. PostgreSQL state/audit/outbox and unique undo links survive restart. |
| A3 | Immutable available observation snapshots, SHA-256/size checks, explicit missing context and numbered timeline revisions. Network evidence is a real MQTT transcript; raw PCAP is unavailable locally. |
| A4 | Same-model peers receive independent 60-minute watch leases after confirmed containment. Overlap, expiry and owner-specific undo replace the effective set safely. Actual model-watch consumers remain external. |
| A6 | One unresolved ticket per device merges drift/loose faults. Three distinct loose episode starts in `(t-30 minutes,t]` trigger a ticket. NORMAL ends an episode, not the ticket; human closure and monotonic revisions are preserved. |
| Lifecycle | Run/reset retire scoped A1 timers and old-run pending outbox, clear active buffers/occurrences/watches and preserve history/isolation. A lifecycle gate prevents reset crossing an in-flight workflow. Only valid new isolated runs restore harness-owned accounts. |
| Offline | Known recording completion retains last readings and offline_since without generating M6 outputs or tickets from silence. |
| Backend reference | Explicit `reference_only=true` local API exposes ward/ticket/action/incident state. Record intake rejects stale runs/revisions; human edits require server-bound biomed identity. Actual public backend/WebSocket/UI are not validated. |

The factory is opt-in, test-only and restricted to loopback and lab-owned inventory. There is no default production containment threshold. Generated lab policy 0.8 is a declared fixture, not a change to M6. The supported deployment topology has one automation worker/scheduler leader.

## Files

New implementation:

- `src/sentinelward/phase4.py`: agent orchestration, durable effects, policy, authorization, tickets, watch leases, lifecycle and undo.
- `src/sentinelward/phase4_state.py`: typed inventory/policy/authorization, state and memory/PostgreSQL repositories.
- `src/sentinelward/phase4_adapters.py`: replaceable ports, real Mosquitto adapter and immutable filesystem evidence.
- `src/sentinelward/phase4_backend.py`, `phase4_factory.py`, `phase4_reference.py`: isolated projection, construction and labelled reference API.
- `migrations/versions/0005_phase4_agents.py`: additive runtime-state table; application rollback preserves history rather than dropping this table.
- `tools/phase4_lab.py`: owned native broker harness with deny-by-default ACLs and private credentials.
- `fixtures/phase4-config.example.json`: explicit placeholders; no credentials or deployment policy.
- Four `tests/test_phase4*.py` files: 29 cases including 25 coordinator cases and four external-integration cases.

Integration changes: `engine.py`, `service.py`, `api.py`, `cli.py`, `config.py`, `alerts.py`, `ports.py`, `persistence.py`, MQTT/alert-publisher adapters, `.env.example` and README. Locked MQTT envelopes and production M6 scoring remain unchanged.

Documentation: [revised plan](phase-4-plan.md), [completion checklist](phase-4-checklist.md), [contracts](phase-4-integration-contracts.md), [runbook](phase-4-runbook.md), and historical [source review](phase-4-source-review.md).

## Exact verification

| Check | Result |
| --- | --- |
| Python 3.12 development interpreter, full pytest with isolated broker/PostgreSQL/VitalDB and research dependencies | **184 passed, 0 failed, 0 skipped**, 156.80 seconds |
| Latest targeted coordinator plus real broker run | **26 passed**, including unacknowledged QoS 1 delivery cleanup and stale containment undo |
| `uv sync --frozen --extra dev` | Passed; locked environment synchronized |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 134 files already formatted |
| `uv run mypy` with repository strict configuration | Passed; 49 source files |
| `uv run sentinelward db upgrade` | Passed through 0005 on dedicated disposable database |
| `uv run sentinelward db init-checkpointer` | Passed |
| `uv run pytest --cov=sentinelward --cov-report=term-missing` with CI-style dependencies | **179 passed, 0 failed, 5 skipped**; 68% whole-package branch coverage |
| Shipped CLI `validate-config` and `serve` | Passed; authenticated status and reference ward API returned 200; unauthenticated internal status returned 401 |
| Frozen source hashes | Both match the checkpoint below |
| `git diff --check` | Passed |

The CI-equivalent run used the same commands and dependency selection locally on Windows. This is not a claim that a new GitHub/Linux workflow has run.

Expected CI-style skips: scikit-learn-dependent forest test; isolated broker test; real broker E2E test; real broker/PostgreSQL restart test; real VitalDB recording integration test. All five ran successfully in the complete development-environment run. Tests do not retrain or alter a deployed model.

The external tests demonstrated actual broker disconnect/reconnect denial, removal of both persistent subscription and an unacknowledged QoS 1 message, PostgreSQL restart durability, and a real MQTT reset/run/vitals/M6/A1/containment/run-again cycle. Unit tests also cover policy boundaries, malformed/unauthorized/stale input, uncertain effects, concurrent duplicates, evidence corruption, watch expiry, ticket closure/undo, urgent output preservation and lifecycle races. No twelve-bed throughput or deployed screen test is claimed.

Artifacts are outside Git under `C:\Users\Aditya\SentinelWard-Phase4-Lab`: `final-full-suite.xml`, `ci-equivalent.xml`, `phase4-verification-summary.json`, `cli-check.json`, `cli-serve.log`, lab broker logs and evidence. Credentials and raw recordings are excluded from the handoff branch. The temporary broker/service/PostgreSQL processes were stopped after verification. The dedicated `sentinel_phase4_20261012` database and its audit history were preserved.

## Frozen research boundary

Production `src/sentinelward/m6.py` SHA-256:

```text
4B1C9084935A8D253FD00D67F9011C464281D79928CBD9A2F4D7C90D2B66C4C7
```

Isolated C1 `C:\Users\Aditya\SentinelWard-M6-Readiness-20261012-01\research\candidates\m6_readiness_candidate.py` SHA-256:

```text
EDE527738073FB8774406773DA4970A8D9EE034CAF78FE185F5D2351ECAFAD9F
```

M6 remains `m6-research-0.3.4`: 900-second baseline, 179 windows, 0.6 drift threshold and 120-second maximum cuff age. No readiness redesign, calibration, retraining or new algorithm experiment was performed. C1 is not merged.

## Remaining acceptance ownership

| Item | Classification | Required action |
| --- | --- | --- |
| Local routing, state, effects, A6, interfaces and lab verification | MY CODE COMPLETE | Review branch and report; no local blocker remains for the agreed local gate. |
| Trusted roles, run binding, record replacement/edit feedback, untrusted/offline projection | BACKEND DEPENDENCY | Implement/accept the documented boundary in the actual backend and public API/update stream. |
| Source identity, run/reset/end and old traffic | SIMULATOR DEPENDENCY | Connect valid fresh episodes and completion behavior; perform team lifecycle smoke test. |
| Deployed broker/evidence/fleet adapters and raw PCAP | KARTIK DEPENDENCY | Review or replace local ports and verify real credentials/session cleanup/evidence access. |
| Approved containment policy and watch consumption | OTHER MODEL/AGENT OWNER DEPENDENCY | Approve versioned policy; connect actual watch consumers without undocumented model changes. |
| TLS, ACLs, service credentials, deployment topology, evidence retention/access | BROKER/DEPLOYMENT DEPENDENCY | Inspect deployed configuration and run authenticated acceptance tests. |
| Antara S6/S7/S9/S11 state and controls | BACKEND DEPENDENCY | Wire screens to accepted public state and role checks; capture actual UI evidence. |
| Shared internal ticket/watch/evidence payloads and source completion transport | CONTRACT AMBIGUITY | Team must accept the documented local proposal; Doc 00 envelopes were not silently expanded. Existing authenticated source-end endpoint/timers are retained. |

The team must also run the [lifecycle smoke test](demo-v1.1-team-smoke-test.md) and Phase 4 containment/undo, BOTH, evidence/watch and ticket scenarios against real backend, simulator and screens. The production 900-second M6 baseline remains a documented limitation of short demo recordings. No algorithm change is justified to close these integration gates.

**Phase 4 local implementation: COMPLETE. Team deployment acceptance: PENDING external owners.**
