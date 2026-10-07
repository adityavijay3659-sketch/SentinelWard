# SentinelWard Phase 0–1 complete technical summary

Prepared: 8 October 2026

Repository: `SentinelWard`

Implementation branch: `phase/1-foundation`

## 1. Project purpose

SentinelWard is Team TessNova's IBM Z Datathon 2026 system for distinguishing among:

- a genuine patient emergency;
- a faulty, loose or gradually drifting sensor;
- tampered or maliciously altered monitor data; and
- a network/device attack that may not represent a patient emergency.

The system does not diagnose a patient and does not control treatment. It coordinates evidence,
alerts, human checks, security containment, reporting and operational follow-up around verdicts
produced by the team's decision layer.

The fundamental safety rule is that security uncertainty must never hide a possible clinical
emergency. A `BOTH` verdict therefore preserves the nurse alert path while separately starting
the eligible security path.

## 2. Status at the end of Phase 1 implementation

| Area | Status | Meaning |
|---|---|---|
| Phase 0 design | Locally complete | Architecture, contracts, responsibilities and safety rules are documented. |
| Phase 0 feasibility | Locally verified | LangGraph persistence, scheduling, Granite, Telegram contract, VitalDB discovery and drift detection toys passed. |
| Phase 0 team confirmations | Pending | Named teammates still need to confirm live credentials, endpoints and owned interfaces. |
| Phase 1 repository implementation | Complete locally | The shared foundation service, database, adapters, deployment files and tests exist. |
| Phase 1 automated verification | Passing | Formatting, typing, unit, contract, security, recovery and PostgreSQL integration tests pass. |
| Live MQTT/backend integration | Pending | No team broker credentials, backend token or approved final endpoint are available locally. |
| LinuxONE deployment | Pending | The systemd and dependency design exists but has not run on the actual VM. |
| Clinical production readiness | Not claimed | The work is a datathon engineering foundation, not a certified medical device. |

## 3. Non-negotiable system rules

1. A patient must never disappear from the central view because data became untrusted.
2. Suspected tampering must never cancel an emergency alert.
3. Every automatic material action must be auditable and idempotent.
4. Reversible actions use a new undo record; history is never rewritten.
5. SentinelWard cannot control medication, pumps, ventilators or treatment.
6. Official incident reports are drafted automatically but sent only by a person.
7. Granite may write narrative text but cannot choose verdicts or operational actions.
8. The automation service reads monitor-derived information but never writes commands to a
   medical monitor.
9. Canonical JSON is the machine interface. Human-readable one-line output is only a projection.
10. Secrets and patient-identifying information must not enter source control or ordinary logs.

## 4. Framework and technology decisions

### 4.1 LangGraph instead of Zapier

LangGraph for Python is the sole workflow/agent framework. It was chosen because SentinelWard
needs typed state, deterministic branches, resumable workflows, PostgreSQL checkpoints,
fine-grained tool permissions, local/LinuxONE deployment and custom MQTT/device adapters.

Zapier is not a runtime dependency. It is appropriate for simple cloud SaaS automation, but it
does not provide the required level of local device integration, restart recovery, custom model
execution, transaction control or least-privilege action policy for this project.

APScheduler was separately validated for persistent timer feasibility. It is a scheduler, not a
second agent framework, and will support the alert ladder and shift deadlines in later phases.

### 4.2 Phase 1 technology baseline

| Concern | Selected technology |
|---|---|
| Runtime | Python 3.12 |
| Workflow orchestration | LangGraph 1.2.14 |
| Durable graph state | `langgraph-checkpoint-postgres` 3.1.2 |
| Database access | Psycopg 3.3.6 and PostgreSQL 17-compatible SQL |
| Wire messaging | MQTT 3.1.1 over TLS using Paho MQTT 2.1.0 |
| Contracts/settings | Pydantic v2 and `pydantic-settings` |
| Internal HTTP integration | HTTPX with explicit authentication, timeouts and retry rules |
| Health API | FastAPI/Uvicorn |
| Migrations | Alembic |
| Dependency management | `uv` with committed `uv.lock` |
| Linux deployment | Python virtual environment and systemd |
| Verification | Pytest, Ruff, MyPy and GitHub Actions |

Docker, Zapier, n8n, Make and a hosted LangGraph control plane are not required by the runtime.

## 5. Team ownership and integration boundaries

### Aditya — automation, agents and M6

- Hosts the shared LangGraph engine, policy guard, persistence and audit foundation.
- Owns A1 with Antra, plus A5, A6, A7 and A8.
- Hosts typed boundaries around Kartik's A2, A3 and A4 handlers.
- Owns Granite narrative generation with deterministic fallback.
- Owns the M6 blood-pressure drift watcher with review from Aditya Singhal.
- Keeps A9 as design-only work during the datathon.

### Aditya Singh — platform/backend

- Owns the simulator, shared MQTT broker, backend and shared PostgreSQL environment.
- Must provide TLS/authentication details, database boundaries, roster/device inventory and
  backend acknowledgement/event endpoints.

### Aditya Singhal — decision/model layer

- Produces canonical final verdicts.
- Reviews the M6 feature, calibration and emergency-safety handoff.
- Must confirm five-second window alignment and provide verdict fixtures/live publications.

### Kartik — cybersecurity

- Owns the A2 containment, A3 evidence and A4 fleet-hunt handler implementations.
- Must provide typed results, error behavior, undo semantics, evidence locations and adversarial
  fixtures.

### Antra — screens and messaging

- Owns screen/Telegram presentation behavior with Aditya.
- Must freeze templates, callbacks, roles and representations of pending, failed, acknowledged,
  untrusted and undone states.

## 6. Phase 0 — theoretical and architecture work

Phase 0 converted the idea into explicit system boundaries before production implementation.

### 6.1 Canonical verdict vocabulary

Only the following verdict values are allowed on the live verdict wire:

- `NORMAL`
- `EMERGENCY`
- `BOTH`
- `TAMPERING`
- `UNSURE`
- `DRIFTING`
- `LOOSE_SENSOR`
- `DEVICE_ATTACK`

`UNTRUSTED` is a display/data-trust state created after containment. It is not a verdict.

Aliases such as “hacked,” “real emergency” and “sensor fault” may appear in human discussion but
must not replace canonical values on MQTT.

### 6.2 Locked messaging design

The service consumes:

- `ward/bed/<bed_id>/verdict`
- `ward/bed/<bed_id>/bedside`
- `ward/bed/<bed_id>/vitals` for the future M6 path
- `ward/bed/<bed_id>/score/M3`
- `ward/bed/<bed_id>/score/M5`

It produces:

- `ward/action`
- `ward/alert`
- `ward/bed/<bed_id>/score/M6`

Vitals use MQTT QoS 0; state-changing and workflow messages use QoS 1. Verdicts are retained,
while action and alert events are not retained.

### 6.3 Correlation and idempotency

- Verdict identity: `bed_id:window_start:verdict`.
- External action identity: `correlation_id:agent_id:action:target_id`.
- A1 keeps one stable alert identity while escalating.
- Retrying a completed request returns its stored state rather than repeating the effect.
- An undo is a new action linked to the original action ID.
- Failed attempts remain visible instead of being replaced by a successful retry.

### 6.4 Agent registry and authority model

| Agent | Purpose | Key authority boundary |
|---|---|---|
| A1 | Nurse/doctor alert ladder | Can alert and record acknowledgement; cannot treat. |
| A2 | Device-client containment | Can isolate an approved client; only IT can undo. |
| A3 | Evidence preservation | Can snapshot/hash/write timeline; cannot contain. |
| A4 | Same-model fleet hunt | Can raise expiring watch levels; cannot isolate another device. |
| A5 | CERT-In report draft | Can populate/start deadline; has no send capability. |
| A6 | Biomed tickets | Can open/update tickets; biomed closes them. |
| A7 | Workload warning | Can warn charge nurse; cannot reassign staff. |
| A8 | Shift briefing | Can collect/write verified facts; cannot modify sources. |
| A9 | Future playbook learning | No datathon runtime actions. |

The policy model is deny-by-default: any action absent from the source-controlled registry is
rejected and audited.

### 6.5 Routing theory

- `NORMAL`: no agent action.
- `EMERGENCY`: A1.
- `BOTH`: A1 and A2 independently; A3/A4 follow successful containment.
- `TAMPERING`: A1 hand-check, A3 evidence and threshold/policy-dependent A2.
- `UNSURE`: A1 bedside hand-check.
- `DRIFTING`: A1 and A6.
- `LOOSE_SENSOR`: A1; A6 after the repetition rule.
- `DEVICE_ATTACK`: IT/security path without creating a nurse-facing clinical alarm solely from
  the network event.

A7 and A8 are scheduled or explicitly requested rather than directly routed from one verdict.

### 6.6 M6 drift-watcher design

M6 answers whether an arterial blood-pressure sensor is slowly becoming inaccurate while its
output remains plausible. It is a model service, not an LLM agent, and cannot issue the final
verdict or perform actions.

Planned input evidence includes:

- arterial waveform and ART systolic/mean/diastolic measurements;
- NIBP cuff systolic/mean/diastolic measurements;
- ART-minus-cuff gap, with 10 mmHg as an initial clinical-rule signal;
- a robust patient-specific baseline;
- Page-Hinkley persistent mean-shift evidence;
- waveform-shape evidence for level shift versus damping; and
- optional aligned M3/M5 cause evidence.

Data is aligned to a common 125 Hz stream and a 10-second window emitted every five seconds.
Patient-wise splits prevent one patient's data from leaking across training/validation/test.

Safety precedence requires zero ordinary-drift calls on the held-out genuine-hypotension safety
set. If cuff, heart-rate and pulse evidence support a real pressure fall, M6 marks the evidence as
emergency-compatible rather than suppressing it. Missing data reduces confidence; it never
becomes a fabricated normal result.

M6 eventually publishes a v1 score containing the calibrated score, label, short reason and
available gap/Page-Hinkley/shape/cause/input-sufficiency evidence. Threshold calibration remains
a later modeling task reviewed by Aditya Singhal.

### 6.7 Deterministic one-line compatibility

All teammate integrations exchange canonical JSON. For human logs, messages and screens, the
automation layer derives:

```text
HH:MM:SS UTC | SUBJECT | SOURCE EVENT | KEY FACT | RESULT_OR_NEXT
```

The renderer:

- uses a fixed template rather than Granite;
- sanitizes tabs and line breaks;
- excludes patient names/PHI;
- keeps canonical IDs and states;
- truncates the key fact before identity/result fields; and
- guarantees one physical line of at most 160 characters.

Fourteen Phase 0 examples cover A1–A8, Granite provenance, M6, verdicts, bedside confirmation and
delivery retry. The longest validated example is 112 characters.

### 6.8 Failure and security theory

Safe degradation was defined before implementation:

- Granite failure uses deterministic templates.
- Telegram failure keeps the central-screen alert active.
- Backend failure uses a durable outbox.
- PostgreSQL failure stops new mutating workflows.
- MQTT failure reconnects without inventing missed verdicts.
- Containment failure is reported as failure, never false success.
- Insufficient M6 evidence abstains or reports insufficiency.

Security design includes separate credentials, least-privilege MQTT ACLs, authenticated backend
events, role-checked approvals, append-only audit behavior and treating every external string as
data rather than instructions.

Required adversarial scenarios include replayed `BOTH`, forged acknowledgement, double undo,
invalid score, clock skew, prompt injection inside a device name, Granite-invented numbers and a
restart immediately before escalation.

## 7. Phase 0 — feasibility evidence

All feasibility toys were deliberately kept outside the project repository.

| Capability | Result |
|---|---|
| LangGraph PostgreSQL pause/restart/resume | Passed |
| APScheduler PostgreSQL persistence/exactly-once toy | Passed |
| Telegram callback/edit-in-place contract | Passed offline |
| Granite 3.3 2B through `llama.cpp` | Passed |
| VitalDB ART/NIBP discovery | 3,024 matching cases identified |
| VitalDB sample read | 11,543 one-second rows; 347 finite NIBP MAP samples |
| Page-Hinkley gradual-shift toy | Stable period clean; shift detected at sample 94 |
| Live Telegram test | Pending credentials |
| LinuxONE compatibility | Pending VM access |

The local feasibility environment used Python 3.12.14, PostgreSQL 17.10, LangGraph 1.2.14,
checkpoint-postgres 3.1.2, Paho MQTT 2.1.0, River 0.26.1 and VitalDB 1.7.2.

## 8. Phase 1 — implemented architecture

### 8.1 Runtime flow

```text
MQTT 3.1.1/TLS
       |
       v
topic/size validation
       |
       v
strict Pydantic contract validation ---- invalid ----> durable dead letter
       |
       v
durable inbox + idempotency check
       |
       v
LangGraph deterministic router
       |
       v
deny-by-default policy guard
       |
       v
action reservation -> typed simulated adapter -> result + append-only audit
```

The MQTT callback performs no clinical or policy logic. With QoS 1, it acknowledges a message
only after durable acceptance or durable rejection. If persistence succeeded but workflow
execution was interrupted, redelivery observes `accepted` rather than `processed` and resumes the
workflow. A later replay of the processed message produces no additional action.

### 8.2 Implemented wire models

Strict Pydantic models now exist for:

- verdicts;
- M1–M6 scores;
- actions;
- alerts;
- bedside checks;
- internal agent events;
- action requests/results; and
- shared workflow state.

They reject unknown fields, invalid enums, incorrect priority/verdict combinations, invalid IDs,
out-of-range probabilities, too many reasons, future window ordering, topic/payload type mismatch,
bed/topic mismatch, model/topic mismatch and payloads larger than 64 KiB.

### 8.3 Implemented deterministic graph

The Phase 1 LangGraph contains routing and authorization/execution nodes. It uses the correlation
ID as the LangGraph thread ID. Operational state is composed of JSON-safe typed data so it can be
checkpointed and recovered.

Phase 1 connects only a simulated action port. This proves routing, policy and exactly-once
reservation without giving the development service Telegram or broker-control authority.

### 8.4 Implemented PostgreSQL foundation

The Alembic migration creates:

| Table | Purpose |
|---|---|
| `automation.ingress_events` | Validated payload, hash, correlation, state and unique ingress key. |
| `automation.dead_letters` | Rejection code/detail, payload hash and bounded diagnostic excerpt. |
| `automation.workflow_runs` | Foundation for summarized workflow state. |
| `automation.action_reservations` | Unique action key, request, result and effect state. |
| `automation.audit_events` | Append-only application audit transitions. |
| `automation.outbox_events` | Unique outbound delivery identity and retry state. |
| `automation.undo_links` | Original action-to-approved-undo relationship. |

LangGraph initializes its own checkpoint tables in the same dedicated database. Schema rollback
is intentionally prohibited because rollback must not erase audit/recovery history; application
rollback restores the previous package while retaining data.

### 8.5 Implemented adapters

#### MQTT

- MQTT 3.1.1 with a stable non-empty client ID.
- Persistent session and documented topic/QoS subscriptions.
- TLS 1.2 minimum and CA verification outside tests.
- Username/password support without logging the secret.
- Exponential reconnect delay.
- Manual acknowledgement only after the async durable handler succeeds.
- Publish acknowledgement with a finite timeout.

#### Backend

- Bearer service authentication.
- `Idempotency-Key` using the stable event ID.
- Explicit request timeout.
- Bounded retry only for network, throttling and server failures.
- No retry for authentication or schema/client errors.
- Sanitized provider error mapping.
- Backend liveness check for readiness.

The client targets the proposed `POST /internal/v1/agent-events`; live usage remains blocked until
Aditya Singh approves or replaces the endpoint.

#### External actions

The safe Phase 1 adapter records an authorized action and returns a typed result. It cannot send a
Telegram message or control Mosquitto. Live adapters replace the port later without changing
router or policy logic.

### 8.6 Configuration and deployment

The CLI provides:

```text
sentinelward validate-config
sentinelward db upgrade
sentinelward db init-checkpointer
sentinelward smoke-test
sentinelward serve
```

Secrets are loaded from environment variables. Demo/design-real profiles require TLS, CA and
MQTT credentials. The Linux deployment uses a non-login `sentinelward` user, systemd restart on
failure, `NoNewPrivileges`, protected filesystem/home settings and a mode-`0600` environment
file.

Operational endpoints are:

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

Readiness reports PostgreSQL, MQTT and backend independently. Metrics contain dependency gauges
and event counters without patient data.

### 8.7 CI and repository quality

The GitHub Actions workflow provisions PostgreSQL 17, installs the frozen dependency set and
runs:

- Ruff linting;
- Ruff formatting verification;
- strict MyPy analysis;
- application migration;
- LangGraph checkpointer initialization; and
- the complete Pytest suite with coverage output.

## 9. Phase 1 verification results

The final local verification produced:

- 28 passing automated tests;
- zero failed or skipped tests when the disposable PostgreSQL server was enabled;
- clean Ruff lint and formatting checks;
- clean strict MyPy analysis of 20 source modules;
- repeatable PostgreSQL migration;
- successful LangGraph checkpoint initialization;
- successful database-backed duplicate smoke test;
- successful source distribution and wheel builds;
- valid JSON, TOML and GitHub Actions YAML; and
- no detected committed credential/private-key patterns.

Behavior covered by tests includes:

- all eight canonical verdict fixtures;
- score/action/alert/bedside contracts;
- malformed JSON, unknown topics and topic/payload mismatches;
- verdict-priority mismatch and payload-size limits;
- `EMERGENCY`, `NORMAL` and `BOTH` routing;
- unauthorized cross-agent and treatment-language rejection;
- one-line sanitation and truncation;
- duplicate verdict suppression;
- dead-letter behavior with zero external actions;
- interrupted ingress recovery;
- backend authentication and network failures;
- health/readiness/metrics behavior;
- MQTT subscription and durable acknowledgement behavior;
- PostgreSQL ingress uniqueness;
- action reservation, audit and outbox uniqueness; and
- recovery across newly created engine/checkpointer instances without a duplicate action.

## 10. Real-time patient data and efficiency

The current automation path is designed for compact events—verdicts, scores, alerts and bedside
confirmations—not one MQTT message per raw waveform sample.

For the datathon target of approximately 8–12 beds and five-second score/verdict windows, the
event workload is small for this architecture. Real-time simulated data that follows the agreed
JSON contracts can be connected without redesigning the router.

Raw ART/ECG/PPG waveform data must be handled by the dedicated model/data pipeline. M6 should
batch and process high-frequency samples, then publish compact five-second results. Sending every
125 Hz sample through LangGraph would be inefficient and is outside Phase 1's design.

Before any real clinical deployment or larger scale, the team must add or verify:

- PostgreSQL async connection pooling;
- a bounded ingress queue and backpressure;
- controlled workflow concurrency;
- batched waveform processing and retention limits;
- encryption and de-identification policy;
- 5–10× synthetic burst/load testing;
- latency and resource measurements on LinuxONE; and
- the required medical, privacy, institutional and regulatory approvals.

No real patient data is required to complete the integration gate. Synthetic or properly
authorized/de-identified replay data is safer and sufficient for functional and load testing.

## 11. Work intentionally outside Phases 0–1

- Live Telegram escalation and acknowledgement ladder: Phase 2.
- M6 training, calibration and evaluation: Phase 3.
- Live A2–A4 containment/evidence/fleet integration and A6 ticket rules: Phase 4.
- A5/A7/A8 and live Granite narrative pipeline: Phase 5.
- Full adversarial/golden-scenario verification: Phase 6.
- Final teammate startup/demo handoff: Phase 7.
- A9 automatic playbook learning: design-only for the datathon.

## 12. Inputs still required from teammates

Phase 1 cannot be called officially complete until the following external work is available:

- LinuxONE login and supported Python/build-tool evidence.
- Shared PostgreSQL database with separate migration/runtime roles.
- MQTT TLS CA, service identity, credentials and least-privilege ACLs.
- Final backend base URL, service token and approved internal-event schema.
- Live current-timestamp verdict publication from Aditya Singhal.
- Final A2–A4 handler contracts from Kartik.
- Screen/Telegram state and callback confirmation from Antra.
- A recorded LinuxONE start/stop/restart and dependency-failure test.

These are integration inputs, not reasons to redesign the locally implemented foundation. If
teammates preserve the agreed contracts, their live components replace the current safe adapters
without changing workflow logic.

## 13. Final conclusion

Phase 0 established a coherent, safety-first theoretical design and demonstrated that the chosen
technologies work locally. Phase 1 converted that design into a tested, packageable, restart-safe
foundation with strict contracts, deterministic routing, policy enforcement, PostgreSQL
persistence, MQTT/backend adapters, deployment material and automated verification.

The repository is ready for teammate integration. It is not yet a fully deployed end-to-end
system because live broker/backend/LinuxONE access and teammate-owned components remain external.
It also does not claim certification for real clinical use.
