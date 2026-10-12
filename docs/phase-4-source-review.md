# Phase 4 reference and repository review

Reviewed 12 October 2026. This records the pre-implementation planning baseline. Later local implementation and evidence are in [phase-4-verification.md](phase-4-verification.md); the code-gap table below is historical. M6/C1 and external Drive/website content remain unchanged.

## Verified starting point

- Repository: `C:\Users\Aditya\SentinelWard`, branch `phase/2-a1-alerts`.
- Published checkpoint: `905235db82070b14a848e3d224643e1a242dc82b`.
- GitHub Actions run [38239788690](https://github.com/adityavijay3659-sketch/SentinelWard/actions/runs/38239788690): success, as verified during the preceding CI repair.
- Local full-data verification before publication: 155 passed, 0 failed, 0 skipped. CI-equivalent environment after repair: 153 passed, 2 expected skips (optional scikit-learn and local VitalDB).
- Production M6: `m6-research-0.3.4`; SHA-256 `4b1c9084935a8d253fd00d67f9011c464281d79928cbd9a2f4d7c90d2b66c4c7` rechecked for this review.
- C1 remains outside production. No further algorithm experiment is part of Phase 4.
- M6 local lifecycle work is complete. Backend/simulator/broker/other-owner reset and public projection acceptance remain open. See the [contract matrix](demo-v1.1-contract-matrix.md) and [reset ownership](demo-v1.1-reset-ownership.md).

## Sources read

Current folder metadata and readable native document content were fetched through the connected Google Drive provider. Eleven relevant documents were read. Updated work plans and Doc 00 control older research prose where they differ; the user's explicit frozen-M6 decision controls all M6 research scope.

| Reference | Version / last Drive modification | Phase 4 evidence used |
| --- | --- | --- |
| [Doc 00: locked integration](https://docs.google.com/document/d/1-Ed1T3W-KtivVRMt5GJGYN9NCGwTv6z7UfOpTC29mAA/edit) | v1.1, 11 Oct 2026 | Topic schemas, ownership, request actor, undo links, records, offline/reset, API boundary. |
| [README first](https://docs.google.com/document/d/1DkydynqUffO-nGMkcH0oaRNfRQSFOKCsYgQmHPTjiv4/edit) | v4, 10 Oct 2026 | Prototype scope, official event schedule; no claim that local coding authorization resolves event eligibility. |
| [Aditya automation work plan](https://docs.google.com/document/d/1g607UAj0qesELA4680IGhnaUZwQg4RjkUWsgmImgdS4/edit) | v3, 10 Oct 2026 | Own agent hosting, action policy/log/undo, A6; integrate Kartik's agents. |
| [Kartik work plan](https://docs.google.com/document/d/1utw4aFgQ8Tsm5EP1mu0xVPkJDaXXFSXG-1foguBwj6w/edit) | v3, 10 Oct 2026 | Own A2/A3/A4, broker disable/enable/session handling, attack and network evidence. |
| [Lead/platform work plan](https://docs.google.com/document/d/1_43FuBBhiW-bTBhmUVhJKH5GqbPPyX32ePCQGEWCTGA/edit) | v3, 10 Oct 2026 | Own simulator, public backend, database deployment, device/state projections and live results. |
| [Antara screen work plan](https://docs.google.com/document/d/1Iqp00wRQVio18b4sI1VrvvRsa_0skvwQ9APc7hWn-zM/edit) | v3, 10 Oct 2026 | Security/incident/ticket/action screens; role visibility; last values retained. |
| [R11 agent details](https://docs.google.com/document/d/1SaD60f1lrpUgjKemy3YoNnE98ERCKBKeA2-usyx_JfY/edit) | v2, last modified 8 Oct 2026 | A2 threshold gate, A3 trigger set, A4 one-hour watch, A6 repeats, allow-lists and safety. |
| [R8 screen specification](https://docs.google.com/document/d/1stFg90DtlCUl52_x2HjPtPDqgkxRchgWUEBULJzNxTc/edit) | v2, last modified 8 Oct 2026 | S6 security, S7 evidence, S9 biomed board, S11 action/undo views and their required fields. |
| [R9 tools/ownership](https://docs.google.com/document/d/1Rav9-wuzY-fMHfCsrsB0T4ooaSBZAa5xLjmkx5F4btk/edit) | v3, last modified 8 Oct 2026 | Python/LangGraph/PostgreSQL continuity; Kartik handlers run in Aditya's engine. |
| [Doc 12 ward script](https://docs.google.com/document/d/1z0aEjihQrE7EuBQyI3UGBkV1MPdTpab0fJKTQnOPMd8/edit) | v1, last modified 10 Oct 2026 | B05 containment/undo, B07 BOTH, B08 ticket, B11 network-only incident; timing evidence. |
| [Doc 13 execution schedule](https://docs.google.com/document/d/14op3VDtirTzZsnxsdOMfuKHp2_K5WQbixNM7uNEP86Y/edit) | v1.1, 10 Oct 2026 | Isolation checkpoint; critical-scope priorities; schedule is an event time box, not a measured implementation estimate. |

Website reference: [SentinelWard Inside](https://sentinelward-inside.vercel.app/#/ring). The live HTML and its referenced JavaScript asset `/assets/index-DaHYyF5z.js` were fetched on 12 October. Relevant A2/A3/A4/A6 content was inspected directly. The website agrees on Kartik's A2–A4 ownership and A6's three loose-sensor occurrences in 30 minutes / any drift / merged biomed ticket behavior. This was content verification, not rendered UI or functional browser testing.

Website asset SHA-256: `b7c5e06368857c66f466749213acc01385b46be009d1d4a00acdb5b1cebbe0a3`.

## Code findings

| Code location | Current behavior | Required Phase 4 work |
| --- | --- | --- |
| `src/sentinelward/router.py` | BOTH -> A1+A2; TAMPERING -> A1+A3; DEVICE_ATTACK -> A3; DRIFTING -> A1+A6; LOOSE_SENSOR -> A1. | Add threshold-gated TAMPERING containment and BOTH evidence; implement downstream A4 and loose-event aggregation. Preserve all A1 routes. |
| `src/sentinelward/phase2_actions.py`, `cli.py` | Only A1 is live. Every other action delegates to `SimulatedActionPort`, which returns completed for recorded intent. | Explicit handler registry; never report a real isolation, evidence completion or ticket merely because intent was simulated. |
| `src/sentinelward/engine.py` | Serial execution; existing non-A1 reservations return duplicate without distinguishing unfinished/failed/unknown effects. | Durable step-aware recovery and independent failure handling; prove recovery at each side-effect boundary. |
| `src/sentinelward/policy.py` | Agent/action allow-list, treatment prohibition, IT role and approver required for `enable_client`. | Preserve controls and obtain role from trusted authorization context; request identity alone is insufficient. |
| `src/sentinelward/service.py` | A1 ack/escalate execute; isolate/undo become `request.not_owned` audit records. | Resolve original owner/action; authorize and dispatch to centralized agent coordinator. |
| `src/sentinelward/contracts.py` | Request has `by` but no role or run identity; strict v1.1 parser. Action has undo fields; record has generic data. | Keep envelopes locked. Propose typed internal handler results and record data separately; agree backend authorization/run-binding semantics. |
| `migrations/versions/0001_phase1_foundation.py` | Action reservations, audit, outbox, and unique undo link table already exist. | Reuse tables where correct; add only missing durable workflow/ticket/expiry state via a new migration. |
| `src/sentinelward/adapters/record_publisher.py` | Validates and delivers agent records; backend same-ID replacement is external. | Use for A3 incidents and A6 tickets. Specify data and revision ordering with backend owner. |
| `src/sentinelward/demo_lifecycle.py` | M6-specific run/reset state and offline enforcement. | Add separate agent lifecycle coordination without changing M6 semantics; preserve historical evidence and clear active timers/counters. |

## Conflicts and unresolved decisions

| Issue | Resolution in this plan |
| --- | --- |
| Older Drive/website M6 text recommends patient-specific calibration. | Superseded by the user's completed research decision. No calibration, C1 merge, threshold or feature change. |
| Local documents still discuss a proposed `/internal/v1/agent-events` write path. | Doc 00 v1.1 supplies `ward/record` for incidents/tickets. Use that locked path; no competing endpoint by default. |
| R8 mentions `/api/fleet-hunt`, Pause/speed control, and a 12-minute script. | These are not in locked v1.1. Do not implement them from old screen prose; Doc 00/12's 20-minute run/reset controls prevail. |
| Ward script mentions A4 for network-only B11, while agent registry/R11 trigger A4 after containment. | Keep successful-containment trigger until lead/Kartik decide an explicit alternative. DEVICE_ATTACK does not automatically imply A2. |
| Registry table puts BOTH evidence after A2, while R11 says any BOTH needs evidence. | Recommend evidence regardless of containment success, with capture before destructive session operations where possible. Confirm ordering with Kartik; never lose evidence because containment fails. |
| Containment threshold and confidence equality are not numeric in locked contract. | Lead/Singhal/Kartik must supply an approved versioned policy. Missing policy disables automatic A2; do not invent 0.8/0.9. |
| `ward/request` contains actor identity without authenticated role. | Agree a protected actor/role lookup or an explicitly approved contract extension. Fail closed for privileged actions until available. |
| Verdict/request/action envelopes have no run ID. | Preserve envelopes. Agree ingress run binding, retained-verdict clearing and cutoff rules before live acceptance. Do not infer stale protection from M6's score-only metadata. |
| Same-record replacement does not specify delayed-revision ordering. | Backend owner must define rejection of older updates and expose biomed edits; this is necessary for reliable repeated-ticket merging. |
| Loose-sensor occurrence versus five-second repeated windows is unspecified. | Proposed behavior is transition/episode-based occurrence counting; confirm at milestone P4-0 and test boundaries. |
| Every action is described as undoable, including immutable evidence and external notifications. | Define reversible state changes and compensation per owner. Never delete audit/evidence or pretend sent notifications can be erased. |

No teammate implementation or deployed ACL was inspected; none is claimed complete. Planning may proceed now, while live integration acceptance remains gated on the listed external evidence.
