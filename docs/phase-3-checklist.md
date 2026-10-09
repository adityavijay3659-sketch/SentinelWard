# Phase 3 completion checklist

## Local implementation

- [x] Drive scope checked against Doc 00 v1, Aditya v3 and R10.
- [x] Strict v1 vitals parsing with finite samples, explicit missing channels and clock checks.
- [x] Causal 125 Hz, 10-second windows every 5 seconds.
- [x] Fresh cuff gap and 15-minute frozen episode baseline.
- [x] Two-sided Page–Hinkley, pressure morphology and timing proxy.
- [x] Patient deterioration and high-alarm precedence, including missing drift inputs.
- [x] Aligned M3/M5 hints with uncertain fallback.
- [x] Bounded PostgreSQL episode state and atomic M6 score outbox.
- [x] Restart, duplicate, concurrent replay and transaction-rollback tests.
- [x] Local VitalDB CSV/gzip and JSONL replay tools.
- [x] Validation-only threshold artifact and patient-separated evaluation.
- [x] Synthetic offset/ramp/damping/tampering/hypotension harness.
- [x] Shared short user/team output policy for all phases; complete model JSON.

## Verification and external acceptance

- [x] Current regression/static/package evidence recorded: 123 tests passed with no skips;
  static checks clean; installed 0.3.1 wheel migrations/checkpointer/smoke and M6 JSON inference passed.
- [x] Twelve real VitalDB subjects replayed; readiness failure retained in the real-data report.
- [x] Separate offline monitor-MAP regression trained with subject-separated validation and testing; research-only weights saved.
- [x] Cold-start cuff-gap assessment fixed without fabricated baseline evidence or weakened patient-review guards.
- [x] New 12-subject research cohort reevaluated; paired regression improvement, uncertainty, missing-subject coverage and controlled drift attribution recorded.
- [ ] Runtime M6 obtains enough fresh-cuff/usable baseline windows on representative recordings (0/12 in both the initial one-hour and new two-hour subsets).
- [ ] Lead supplies and reviews episode lifecycle, clock and monitor mapping.
- [ ] Singhal confirms peer label semantics and M6 score handoff.
- [ ] Independent patient-wise splits and adjudicated labels supplied.
- [ ] Combined threshold selected on actual validation records.
- [ ] Held-out genuine hypotension set has zero false drift calls, with size/uncertainty reported.
- [ ] Real drift sensitivity, detection delay, missing-data behavior and throughput measured.
- [ ] LinuxONE/broker/backend integrated test passes.
- [ ] Singhal and lead sign off the Phase 3 gate.

Local software completion and official Phase 3 acceptance are separate states.
Latest evidence and unresolved coverage: [M6 revalidation](m6-revalidation-2026-10-09.md).
Synthetic results do not close the real-data gate. Publishing this research
implementation does not authorize clinical deployment or close external gates.
