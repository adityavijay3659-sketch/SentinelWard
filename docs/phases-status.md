# Current phase status — 16 October 2026

| Phase | Local work | Remaining acceptance |
|---|---|---|
| 0: contracts and foundation plan | Independently executable work verified | Teammate sign-off, live access and paper walkthrough |
| 1: engine and persistence | Implemented; covered by current regression suite | LinuxONE, authenticated live broker/backend and whole-team gate |
| 2: A1 alert ladder | Implemented; covered by current regression suite | Live screen plus phone, credentials, acknowledgements and restart gate |
| 3: M6 research scorer and demo lifecycle | Local implementation complete; production m6-research-0.3.4 frozen; 24-patient research cycle closed; run/reset/offline contracts implemented | Production full baseline/combined execution was 0/24 on the audited cohort. Cuff reference limitations remain; C1 is isolated and not merged. Deployed owner integration and clinical acceptance are not complete. No further tuning cycle is planned. |
| 4: A2–A4 and A6 | Implemented and locally verified; real isolated broker/PostgreSQL, evidence, authorized undo, watch leases, tickets and agent reset; 184 tests passed | Deployed backend/screens, adapters, source metrics, approved policies and whole-team acceptance remain external. |
| 5: A5/A7/A8 and Granite | Local A5/PDF/human workflow, A7 counts/warnings, A8 facts/briefings and recovery complete; 229 tests passed with no failures/skips. Strict Granite generation 20/20 plus original 30/30; production M6/C1 unchanged. | Template mode ready. The final bounded local contention comparison passed; this does not close full-system or target-host acceptance. Backend/S8/S10/source/LinuxONE and full-team integration remain Phase 6 dependencies. See Phase 5 verification. |
| 6: integrated verification | Local acceptance tools, private profile/snapshot/observer/metrics and LinuxONE operator guide implemented; 245 tests passed, zero failures/skips; lint/format and strict mypy passed. M6/C1 remain frozen. | User-operated LinuxONE and real backend/simulator/models/UI acceptance pending; Telegram intentionally simulated. Actual 20-minute connected demo remains NOT RUN. |
| 7: submission handoff | Planned | Full service startup/reset/run evidence and teammate-led demonstration |

Phase 5 checkpoint: `9bd9ffb` on `phase/5-narrative-agents`. Phase 6 verification builds on it
on `phase/6-verification`. These are separate publication branches; `main` is not merged
or deployed. The Phase 4 base remains `e01e090`; Phase 3 remains `phase/3-m6` at `905235d`.
Current Phase 4 evidence: [verification and external dependencies](phase-4-verification.md).
Phase 5 [final plan](phase-5-plan.md), [verification](phase-5-verification.md), [contracts](phase-5-contracts.md), [runbook](phase-5-runbook.md) and [checklist](phase-5-checklist.md) distinguish implementation from model and external acceptance. Verification reports describe the pre-publication evidence checkpoint; consult GitHub for current branch heads and CI status.

Phase 6 local tooling is on `phase/6-verification`. See [measured verification](phase-6-verification.md),
[operator instructions](phase-6-linuxone-operator-guide.md) and [owner checklist](phase-6-checklist.md).
The user operates LinuxONE; no project code runs there before the event permits it.
Phase 7 remains a separate final handoff/submission phase.

Historical real-data evidence: [training, runtime readiness failure and connectivity checks](real-data-verification-2026-10-09.md).
Historical M6-only evidence: [revalidation, measured improvement, remaining failures and clinical evidence](m6-revalidation-2026-10-09.md).
Current M6 software repairs and verification: [10 October repair evidence](m6-repairs-2026-10-10.md). Clinical and external acceptance remain pending.
Earlier software evidence: [92 passing tests and installed package checks](phase-3-verification.md).
The synthetic 12-scenario M6 harness does not complete Phase 6's integrated golden
demonstration. Official completion depends on each original phase gate, including
the external items in the [Phase 0](phase-0-checklist.md), [Phase 1](phase-1-checklist.md),
[Phase 2](phase-2-checklist.md) and [Phase 3](phase-3-checklist.md) checklists.

The [output requirements](one-line-output.md) apply to all phases: deterministic
short human/team views, explicit urgency and evidence-backed state, complete
typed machine output, and clear missing/unvalidated information. Phone delivery
continues as a backup channel. Future implementation must satisfy those rules
before its phase acceptance gate can pass.

The Phase 2/3 checkpoint and Doc 00 v1.1 lifecycle integration are published on
`phase/2-a1-alerts` and `phase/3-m6`; Phase 4 builds on that checkpoint. Publication
does not close the live integration or clinical acceptance gates listed above.

For detailed continuation context, see the
[dated master handoff](new-chat-handoff-2026-10-09.txt). Its Git-state section is a
historical snapshot; inspect current Git state when resuming.
