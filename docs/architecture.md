# Automation architecture

Status: Phase 0 design baseline. The MQTT v1 interfaces are locked; the internal backend ingestion interface is proposed and requires Aditya Singh's approval.

## Framework decision

Use **LangGraph for Python** as the only agent workflow framework.

Reasons:

- explicit state graphs suit allow-listed, auditable workflows;
- interrupts support resumable human approval;
- PostgreSQL checkpointing supports restart recovery;
- it can run locally on LinuxONE without a cloud control plane;
- Python adapters work with MQTT, FastAPI, Telegram, PostgreSQL and Kartik's handlers;
- Granite can be isolated to writer nodes rather than placed in control of actions.

BeeAI, n8n, Zapier and Make are not runtime dependencies. A future n8n diagram may be used as a video illustration, but it is not part of the operating system.

## Runtime boundaries

```text
Aditya Singh: simulator + MQTT + backend + PostgreSQL
                  |
                  | ward/bed/<id>/verdict
                  v
        Aditya: automation service
  validate -> deduplicate -> route -> authorize
       |          |           |          |
      A1       A2-A4        A5-A8       M6 service
       |       (Kartik)      (Aditya)     |
       +---------- actions/events --------+
                  |
                  v
       backend persistence and screens
                  |
          Antra's web UI/Telegram
```

Aditya Singhal's decision layer is the sole source of final clinical/security verdicts. The automation service may reject, route or act on a verdict, but it must never revise it.

M6 is a model service, not an LLM agent. It publishes a score to the decision layer. The decision layer retains authority over the final verdict.

## Automation-service components

1. **Ingress adapter**
   - subscribes to locked MQTT topics;
   - validates `v`, `type`, timestamps, identifiers and enum values;
   - converts documented prose aliases only in test/import tools, never silently on the live wire;
   - sends invalid input to a dead-letter log without triggering an action.

2. **Idempotency layer**
   - verdict key: `bed_id + window_start + verdict`;
   - external side-effect key: `correlation_id + agent_id + action`;
   - retries return the original result instead of repeating an action.

3. **LangGraph router**
   - deterministic conditional edges select eligible agents;
   - `BOTH` fans out to A1 and A2 concurrently;
   - each agent is a subgraph with typed state;
   - an agent cannot discover or call actions outside its registry.

4. **Policy guard**
   - checks agent identity, allow-list, role, approval and current state;
   - refuses and logs every unsupported request;
   - has no treatment-related tools.

5. **Persistence and scheduling**
   - LangGraph `AsyncPostgresSaver` stores workflow checkpoints;
   - APScheduler with a PostgreSQL job store holds alert and shift deadlines;
   - no safety-critical timer is stored only in process memory;
   - restart recovery reconciles pending checkpoints and scheduled jobs.

6. **Outbound adapters**
   - MQTT publisher for locked `ward/action` and `ward/alert` messages;
   - Telegram adapter for A1;
   - Mosquitto control adapter used only by Kartik's A2 handler;
   - internal backend event adapter for reports, tickets, workload and briefings;
   - deterministic one-line presentation renderer for logs, screens and handoff evidence;
   - Granite writer adapter with a deterministic template fallback.

The one-line renderer consumes validated typed events after policy/routing decisions. It is a display projection only: integrations continue to exchange canonical JSON, and no workflow may parse the line to make a decision.

## Configuration profiles

Safety logic is identical in every profile.

| Profile | Timing and endpoints | Purpose |
|---|---|---|
| `test` | virtual clock, fake MQTT/Telegram/backend | deterministic automated tests |
| `demo` | 30-second ladder steps, real demo services | judge-visible run |
| `design-real` | 60-second ladder steps, placeholder hospital adapters | documents intended real deployment |

Configuration may change timing, URLs and credentials. It may not change allow-lists, emergency precedence or human-approval rules.

## Critical path

1. Contracts and fixtures.
2. Engine skeleton, policy guard and audit.
3. A1 end-to-end alert.
4. M6 first validated score.
5. A2/A3 integration and A6 tickets.
6. A5/A7/A8 and Granite fallback.
7. Failure tests and full demonstration.

A9, predictive maintenance and n8n visualization remain outside the critical path.
