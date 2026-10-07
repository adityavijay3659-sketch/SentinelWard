# Phase 1 implementation and team handoffs

## Implemented locally

- Python package, locked environment, CLI and Linux systemd unit.
- Strict Pydantic models for verdict, score, action, alert, bedside and internal events.
- Canonical topic validation, payload cap, correlation and idempotency keys.
- Deterministic LangGraph router and deny-by-default policy guard.
- PostgreSQL migration, AsyncPostgresSaver initialization and restart-safe thread IDs.
- Inbox deduplication, dead letters, action reservations, audit records and outbox schema.
- MQTT 3.1.1/TLS adapter with persistent identity, reconnect backoff and manual acknowledgement.
- Authenticated backend client with timeouts, idempotency header and bounded safe retries.
- Safe simulated action adapter; no live Telegram or device-control capability.
- JSON logs, liveness, readiness and metrics.
- Unit, contract, security, adapter and PostgreSQL integration tests.

## Teammate handoffs required for the live gate

### Aditya Singh

Provide the LinuxONE login, PostgreSQL database/roles, MQTT host/port/CA/service identity/ACLs,
backend base URL/token and written approval or replacement of the internal event endpoint. Run
the migration role separately from the runtime role.

### Aditya Singhal

Publish current-timestamp v1 verdicts to the staging broker and confirm the exact five-second
window convention. Replayed payloads must preserve the same idempotency fields.

### Kartik

Approve the typed A2–A4 request/result/error boundary. Phase 1 uses the safe simulated action
port; real containment authority is not connected until Phase 4.

### Antra

Confirm the UI states for pending, failed, acknowledged, untrusted and undone. Consume canonical
JSON plus the derived one-line view; never parse the line back into decisions.

## Integration sequence

1. Install Python 3.12 and project dependencies on LinuxONE.
2. Create the database with separate migration/runtime roles.
3. Run `sentinelward db upgrade` and `sentinelward db init-checkpointer` as the migration role.
4. Install the environment file and CA certificate with owner-only permissions.
5. Install and start `deploy/sentinelward.service`.
6. Verify liveness, then readiness.
7. Publish one `EMERGENCY`, its exact duplicate, one malformed message and one `BOTH` fixture.
8. Restart the service between checkpoint and completion in a controlled staging run.
9. Record database rows, correlation IDs, metrics and one-line outputs as gate evidence.

## Acceptance outcomes

- One allowed A1 simulated action for the first emergency; none for its replay.
- `BOTH` records independent A1 and A2 branches without suppressing A1.
- An unauthorized cross-agent action is rejected and audited.
- Malformed input is dead-lettered and acknowledged only after persistence.
- Restart resumes the same LangGraph thread and produces no duplicate reservation.
- Backend accepts a valid authenticated event and rejects invalid/unauthenticated events.
- Loss of a dependency makes readiness fail without inventing a successful action.
