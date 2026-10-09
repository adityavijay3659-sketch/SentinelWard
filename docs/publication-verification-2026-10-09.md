# Publication verification — 9 October 2026

This publication includes the Phase 2 A1 alert implementation, Phase 3 M6
research implementation and revalidation tooling, contract/output corrections,
migrations, fixtures, tests and detailed continuation documentation.

Branch: `phase/2-a1-alerts`. No merge into `main` is included.

## Checks rerun before publication

- Full pytest suite: **123 passed, 0 failed, 0 skipped, 44.87 seconds**.
- PostgreSQL integration and local VitalDB recording integration enabled.
- All three migrations and the LangGraph checkpointer initialized on a new
  disposable local test database.
- Ruff lint: passed.
- Ruff formatting: **95 files already formatted**.
- Mypy: **no issues in 40 source files**.
- `uv lock --check --offline`: passed.
- `git diff --check`: passed.
- Known credential-pattern scan: no matches. This is a scoped publication
  safeguard, not a comprehensive security audit.

The initial run had 117 passes and six database-integration failures because
the fresh test database had not been initialized. The verification command
incorrectly used `python -m sentinelward.cli`, which does not invoke the CLI
entry point. Invoking `sentinelward.cli.main` explicitly applied the migrations
and initialized the checkpointer; the entire suite was then rerun successfully.
No application code was changed to mask those failures.

Final JUnit evidence remains local at
`D:/SentinelWard-Phase2-Cache/publication-tests-final-20261009.xml`.

## Scope and remaining gates

No model was retrained for this publication. The latest saved offline research
MAE remains **8.5539 mmHg**, full runtime baseline readiness remains **0/12
subjects**, and clinically reviewed drift/hypotension evidence is still missing.
See [M6 revalidation](m6-revalidation-2026-10-09.md) and
[phase status](phases-status.md) for limitations and external acceptance gates.

The checks do not prove authenticated live MQTT/backend/Telegram connectivity,
LinuxONE deployment, real phone/screen delivery or clinical readiness. No live
clinical notifications, device commands or deployment were performed.

Raw datasets, trained weights, protected configuration, tokens, logs, test
databases, virtual environments and generated test artifacts are not published.
Reproduction code, synthetic/example fixtures and measured-result documentation
are included. The offline research weights are not installed into runtime M6.

## Workspace provenance

C: had no free space. Publication therefore used
`D:/SentinelWard-Publish-20261009-223324`, cloned without hardlinks from the
original workspace and populated with hash-verified tracked/nonignored files.
The original `C:/Users/Aditya/SentinelWard` worktree and Git state were left
untouched. Only publication documentation was adjusted in the D: copy.

The [master handoff](new-chat-handoff-2026-10-09.txt) preserves the detailed
pre-publication snapshot, with a publication note. Check the current remote
branch rather than treating its historical Git-state section as current.
