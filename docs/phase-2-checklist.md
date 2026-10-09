# Phase 2 completion checklist

## Implemented and locally verified

- [x] Locked v1 ladder restricted to three steps.
- [x] Locked bedside results restricted to `patient_ok` and `patient_not_ok`.
- [x] One active alert per bed event with repeat update and priority-upgrade behavior.
- [x] High ladder: assigned nurse, next nurse, then all nurses plus doctor.
- [x] Medium/low one-recipient notification without timed escalation.
- [x] PostgreSQL alert, delivery, callback-token, callback-receipt and roster state.
- [x] APScheduler PostgreSQL timer survives scheduler restart and fires once in the integration
  test.
- [x] Screen acknowledgement and manual escalation internal endpoints with bearer authentication.
- [x] Telegram text/photo delivery, four opaque-token buttons and edit-in-place acknowledgement.
- [x] Per-chat one-message-per-second limiter and bounded `RetryAfter` handling.
- [x] `Patient OK` closes; `Patient NOT OK` raises or upgrades a high alert.
- [x] Screen alert remains active when Telegram fails.
- [x] Deterministic one-line alert output remains one line and at most 160 characters.
- [x] User, team and model output views remain distinct without changing locked v1 MQTT JSON.
- [x] Telegram send/edit, escalation and acknowledgement outcomes publish through `ward/action`.
- [x] Duplicate completed acknowledgement returns stored state without replaying side effects.
- [x] Built wheel contains Alembic migrations and can upgrade a clean database after installation.
- [x] Unit, contract, lint, formatting, typing and PostgreSQL integration checks pass.

## Live team gate still required

- [ ] Aditya Singh supplies MQTT TLS, PostgreSQL and backend service credentials.
- [ ] Backend implements the roster and waveform endpoints in the Phase 2 contract.
- [ ] Backend consumes `ward/alert`, pushes it through `/ws`, and forwards screen ack/escalate.
- [ ] Antara confirms final wording and all screen states against the live payload.
- [ ] Telegram bot token and the protected staff/chat map are installed on LinuxONE.
- [ ] One live verdict reaches both the screen and assigned nurse's phone.
- [ ] A live 30-second escalation reaches all three levels.
- [ ] Screen and Telegram acknowledgement each edit messages, stop escalation and record response
  time.
- [ ] Service restart immediately before escalation produces no duplicate.

Phase 2 is locally implemented but must not be called officially complete until every live-team
gate above passes.
