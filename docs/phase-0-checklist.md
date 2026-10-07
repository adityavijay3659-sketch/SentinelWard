# Phase 0 completion checklist

Date opened: 7 October 2026.

Phase 0 is complete only when every required item below is checked. Documentation prepared in this repository does not by itself prove external access or teammate agreement.

## Completed locally

- [x] Repository created and the approved initial Phase 0 commit pushed.
- [x] Pre-17 October no-code rule recorded.
- [x] LangGraph selected as the sole runtime framework.
- [x] Runtime boundaries and critical path documented.
- [x] Canonical verdict names and `UNTRUSTED` state distinction documented.
- [x] Agent ownership, triggers, allow-lists and human boundaries documented.
- [x] Team input/output handoffs and integration checkpoints documented.
- [x] M6 data, method, safety precedence and evaluation plan documented.
- [x] Failure, degradation and prompt-injection policies documented.
- [x] Canonical v1 example fixtures prepared.
- [x] One-line presentation compatibility defined without changing the locked v1 JSON.
- [x] Per-automation one-line examples validated as single-line output within 160 characters.

## Required teammate confirmations

- [ ] Aditya Singh confirms MQTT access details and PostgreSQL boundary.
- [ ] Aditya Singh approves or replaces the proposed internal agent-event endpoint.
- [ ] Aditya Singh supplies roster and device-inventory fixtures.
- [ ] Aditya Singhal supplies one fixture for every verdict and confirms window alignment.
- [ ] Aditya Singhal accepts the M6 review and threshold-calibration handoff.
- [ ] Kartik confirms A2–A4 handler interfaces, errors and undo behavior.
- [ ] Kartik supplies slow malicious drift and prompt-injection fixtures.
- [ ] Antra freezes Telegram templates, callbacks and UI state expectations.

## Environment and toy-learning evidence

These exercises must be unrelated toys outside this repository.

- [x] LangGraph interrupt/resume survives a local PostgreSQL-backed process restart.
- [x] APScheduler PostgreSQL job survives a scheduler restart and fires once.
- [x] Telegram button payload and edit-in-place behavior pass offline with the real library.
- [ ] Live Telegram send/edit passes using a real bot token and test chat.
- [x] IBM Granite 3.3 2B GGUF runs through `llama.cpp` on the local test machine.
- [x] VitalDB exploration identifies usable ART + NIBP cases.
- [x] Toy Page-Hinkley example detects a controlled gradual shift without firing on stable input.
- [ ] LinuxONE Python and package-install compatibility is checked when access opens.
- [x] Passing local dependency versions and platform observations are recorded without committing project code.

## Phase 0 exit review

- [x] All locked versus proposed contracts are clearly labelled.
- [x] Human-readable output compatibility is documented and fixture-testable.
- [ ] Every live dependency has a fixture or mockable adapter boundary.
- [x] At the Phase 0 exit, no production code, secrets, patient data, model binary or generated evidence existed in the repository.
- [ ] Whole-team paper walkthrough completed.
- [x] Aditya explicitly authorized the first commit/push.

All independently executable work on Aditya's current machine is complete. The repository remains **Phase 0 locally verified, external access and team validation pending**. Later changes are pushed only when Aditya explicitly requests it.
