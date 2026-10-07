# Phase 1 completion checklist

Opened: 8 October 2026.

## Local implementation

- [x] Phase 1 feature branch created without overwriting Phase 0 work.
- [x] Python 3.12 package and reproducible dependency lock created.
- [x] Locked v1 message validators implemented.
- [x] Deterministic LangGraph router and policy registry implemented.
- [x] PostgreSQL application migration implemented and applied locally.
- [x] LangGraph PostgreSQL tables initialized locally.
- [x] Ingress, dead-letter, action, audit and outbox persistence implemented.
- [x] MQTT 3.1.1/TLS adapter implemented.
- [x] Authenticated backend adapter implemented with bounded retries.
- [x] Safe simulated Telegram/device action boundary implemented.
- [x] Health, readiness, metrics and JSON logging implemented.
- [x] Unit and contract suites pass locally.
- [x] PostgreSQL idempotency integration test passes locally.
- [x] Database-backed duplicate smoke test passes locally.

## Live whole-team gate

- [ ] Aditya Singh supplies LinuxONE access and supported Python/package evidence.
- [ ] Aditya Singh supplies the PostgreSQL database and separate migration/runtime roles.
- [ ] Aditya Singh supplies MQTT TLS credentials and least-privilege ACLs.
- [ ] Aditya Singh approves or replaces `POST /internal/v1/agent-events`.
- [ ] The authenticated live backend success/rejection contract passes.
- [ ] Aditya Singhal publishes current-timestamp verdict fixtures through the live broker.
- [ ] Kartik signs off the A2–A4 typed adapter boundary.
- [ ] Antra signs off the screen state and one-line presentation boundary.
- [ ] LinuxONE systemd start, stop and restart tests pass.
- [ ] Restart during a workflow produces no duplicate action.
- [ ] Live dependency failure states appear correctly in readiness and metrics.

Phase 1 is **locally implemented but not officially complete** until every live whole-team gate is
checked. No result in this file claims LinuxONE, live broker or live backend verification.
