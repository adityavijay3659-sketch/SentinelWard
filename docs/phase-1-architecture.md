# Phase 1 foundation architecture

Status: implemented locally; live team infrastructure and LinuxONE acceptance remain pending.

## Runtime shape

SentinelWard uses one Python 3.12 modular service. LangGraph owns deterministic workflow state;
PostgreSQL owns checkpoints, ingress deduplication, action reservations, audit events and the
outbox. MQTT 3.1.1 over TLS remains the team wire. FastAPI exposes only health and metrics.

```text
MQTT/TLS -> validate -> durable inbox -> LangGraph router -> policy guard
             |                                  |
             +-> dead letter                    +-> action reservation
                                                        |
                                              simulated typed adapter
                                                        |
                                                append-only audit
```

The MQTT callback performs no workflow logic. It hands the payload to the asynchronous message
service and acknowledges QoS 1 only after the message is durably accepted or durably rejected.
Duplicate messages return the stored state without repeating an effect.

## Module boundaries

- `contracts`: locked v1 types, topic matching, correlation and idempotency keys.
- `router`: deterministic verdict-to-agent requests; it never changes a verdict.
- `policy`: immutable deny-by-default action registry and human-role boundaries.
- `engine`: LangGraph nodes for routing, authorization and typed action execution.
- `persistence`: in-memory test store and PostgreSQL implementation.
- `adapters`: MQTT, authenticated backend delivery and safe Phase 1 simulated effects.
- `service`: validation, dead-lettering, deduplication and graph invocation.
- `api` and `health`: liveness, readiness and dependency/event metrics.

## Persistence guarantees

The application schema contains ingress events, dead letters, workflow summaries, action
reservations, audit events, outbox events and undo links. LangGraph manages its own checkpoint
tables in the same dedicated database.

Unique keys enforce:

- one ingress record per `bed_id:window_start:verdict`;
- one action reservation per `correlation_id:agent_id:action:target_id`;
- one outbox record per delivery identity.

Audit events are append-only at application level. An undo is a new action linked to its
original; it never edits history. A dangerous action with an unknown external result must be
reconciled instead of blindly retried.

## Security boundaries

- TLS verification is mandatory outside the test profile.
- MQTT, backend and database credentials are independent and never logged.
- The runtime policy cannot be expanded through environment variables.
- The Phase 1 action adapter records intent but performs no Telegram or broker-control effect.
- Payloads larger than 64 KiB are dead-lettered by hash and bounded excerpt.
- LangGraph strict MessagePack deserialization is enabled by the service commands.
- The service has no treatment, medication, pump or ventilator capability.

## Public operational endpoints

- `GET /health/live`: process liveness.
- `GET /health/ready`: PostgreSQL, MQTT and backend dependency state.
- `GET /metrics`: Prometheus text counters without patient data.
- `POST /internal/v1/agent-events`: client implemented against the proposed contract; live use
  remains blocked until Aditya Singh approves or replaces it.
