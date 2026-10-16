# Phase 5 source review — 13 October 2026

Planning baseline: `e01e0905206b92098e40f8a047ac0f20f0e677d8`, branch `phase/4-agent-integration`. No Phase 5 runtime code has been implemented. Source snapshots are held outside Git in `C:\Users\Aditya\SentinelWard-Phase5-Planning`, with hashes in `source-manifest.json` and `technical-source-manifest.json`.

## Sources accessed for this plan

The connected Drive app is unavailable in this session. The public folder and Google Docs text-export endpoints were readable. This is a fresh read of the shared documents, not an assertion that authenticated comments, revision history or private children were inspected.

| Source | Relevant findings |
| --- | --- |
| [Doc 00 v1.1 LOCKED](https://docs.google.com/document/d/1-Ed1T3W-KtivVRMt5GJGYN9NCGwTv6z7UfOpTC29mAA/edit) | `ward/record` already supports A5 report, A7 workload and A8 briefing. The four `ward/request` actions exclude report confirmation, mark-sent and generate-briefing. Public report GET/PATCH/mark-sent APIs are backend-owned. Preserve existing MQTT envelopes. |
| [Aditya work plan v3](https://docs.google.com/document/d/1g607UAj0qesELA4680IGhnaUZwQg4RjkUWsgmImgdS4/edit) | Own A5/A7/A8 and Granite; six-hour report clock; more than 40 alarms in two hours; numeric verification and templates. Later M6 calibration suggestions are superseded by the user's frozen-research decision. |
| [R11 agents](https://docs.google.com/document/d/1SaD60f1lrpUgjKemy3YoNnE98ERCKBKeA2-usyx_JfY/edit) | A5 triggered by IT confirmation; countdown from notice time. A7 every minute, warning-only. A8 at shift end/on demand. Every action audited, authority bounded. |
| [R8 screens v2](https://docs.google.com/document/d/1stFg90DtlCUl52_x2HjPtPDqgkxRchgWUEBULJzNxTc/edit) | S8 editable report, PDF, checklist and human mark-sent. S10 briefing/workload. Explicitly defers to Doc 00 on conflicts. |
| [R9 tools v3](https://docs.google.com/document/d/1Rav9-wuzY-fMHfCsrsB0T4ooaSBZAa5xLjmkx5F4btk/edit) | Python/LangGraph, local Granite via llama.cpp, PDF tooling and deterministic fallback. No required cloud workflow service. |
| [Lead work plan](https://docs.google.com/document/d/1_43FuBBhiW-bTBhmUVhJKH5GqbPPyX32ePCQGEWCTGA/edit), [Antara work plan](https://docs.google.com/document/d/1Iqp00wRQVio18b4sI1VrvvRsa_0skvwQ9APc7hWn-zM/edit) | Backend owns public API, roster, logs and results. Antara owns S8/S10 and role-based presentation. |
| [Ward script](https://docs.google.com/document/d/1z0aEjihQrE7EuBQyI3UGBkV1MPdTpab0fJKTQnOPMd8/edit) | T+19:00 briefing; T+20:00 stop/reset. Expected outputs are scenario targets, not measured facts. Automatic A5 wording conflicts with R11's IT-confirmation trigger. |
| [LinuxONE test results](https://docs.google.com/document/d/1tt4SeUYELCqgt9N85cnZEuK72tOWqFlOInbSaqgJyXA/edit) | Team-reported dummy-data Granite 2B latency supports background report/briefing generation. Measurements were not reproduced here and do not validate this application. |
| [Readiness questions](https://docs.google.com/document/d/1l4o1KZO7Rm5z_Qs246MrksRYoARdpmfjGc74eLKQRM8/edit) | Deployment/lab access remains a team boundary. Historical event restrictions do not override the user's authorization for local planning/work. |
| [SentinelWard website](https://sentinelward-inside.vercel.app/#/ring) | Reviewed current bundle `index-DaHYyF5z.js`: A5/A7/A8/Granite, S8/S10, ownership and links. Website is explanatory; locked contracts and later user decisions take precedence. |

## Current code and available tools

- Python 3.12 service, LangGraph/checkpointer, PostgreSQL audit/outbox, typed contracts, A1 and Phase 4 are implemented. Last complete local regression: 184 passing tests, no skips. This planning step does not rerun that suite or claim newer runtime verification.
- `RecordMessage` validates owner/type and finite JSON but `data` is generic. Phase 5 needs dedicated typed data models inside that envelope, explicit run identity and increasing revision.
- `RequestMessage` is locked to ack/escalate/isolate/undo. New human controls should use authenticated internal HTTP commands through the backend; do not add MQTT actions without a contract decision.
- `RosterSnapshot` contains assigned/next/unit nurses, doctor, version and expiry. It lacks charge-nurse identity, event-time staff membership and shift boundaries. Proposed Phase 5 adapter must supply these separately.
- A1 stores distinct alerts, routing, delivery and acknowledgements. `ward/alert` does not carry run identity or trustworthy staff roles; local durable records are a stronger source than reconstructed MQTT-only counts.
- Phase 4 stores incidents/evidence/actions/tickets and current untrusted/offline state. It does not expose a complete historical trusted-coverage interval ledger or adjudicated suppression events. Current snapshots cannot establish historical Blind Time or true false alarms avoided.
- `MqttRecordPublisher` exists. Its generic correlation key does not itself retire old-run publications; Phase 5 must use run-aware transactional publication rather than assuming this adapter provides reset safety.
- No completed A5/A7/A8 or Granite production writer exists. Existing permission entries are declarations, not proof of handlers.
- Local binary: `D:\SentinelWard-Phase0-Lab\llama.cpp\llama-server.exe`, build 11433, commit `50569eb87`. Local model: `D:\SentinelWard-Phase0-Lab\models\granite-3.3-2b-instruct-Q3_K_S.gguf`. Its hash was remeasured as `CA71C0FAAEA5647C6F34BB55D8AE9516E94828E0065CDBBF4680348BE2BBBFD3`, matching the Phase 0 artifact. No inference benchmark was run during planning; chat/server/config verification remains an implementation gate. No new model training/download is required by this plan.

## Authoritative technical checks

- [IBM Granite 3.3 2B model card](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct): supports instruction-following and summarization; model capability does not establish factual correctness for SentinelWard. Use its chat template and explicitly disable thinking for the bounded writer after testing the pinned server/model combination.
- [Pinned llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/50569eb87/tools/server/README.md): chat endpoint and schema-constrained response format are available. JSON shape constraints do not validate the truth of a sentence. The implementation must test the request against this exact build.
- [Official s390x guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build-s390x.md): model byte order and platform build matter. Local Windows success does not prove LinuxONE compatibility or acceleration. Pin the deployed build and appropriate model hash separately.
- [CERT-In directions](https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf), [FAQ](https://www.cert-in.org.in/PDF/FAQs_on_CyberSecurityDirections_May2022.pdf), [current form](https://www.cert-in.org.in/PDF/certinirform.pdf): use a separate notice-time anchor and human review. The directions' notice-time rule and FAQ Q30's available-information/follow-up allowance were checked in locally extracted official PDFs. Draft completeness is not a legal reportability decision or proof of submission. Map the project field list to a pinned form version rather than calling the older document layout the current official form. Do not make missing fields an implicit instruction to delay human reporting.
- [MeitY final DPDP Rules notification](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf): web extraction failed, but the official PDF was downloaded and its English text extracted locally. The 13 November 2025 notification specifies eighteen-month commencement for rules including breach-intimation Rule 7. The project's 13 May 2027 date is the resulting calendar calculation, not a statement that every DPDP provision begins then. Preserve this primary-source/provision-specific note and recheck it before deployed use; Granite does not supply legal dates or conclusions.

## Ambiguities and proposed resolution

| Issue | Proposed treatment / decision needed |
| --- | --- |
| Draft on machine incident versus IT confirmation | Ask Aditya; recommended IT confirmation, with first observation separately recorded as provisional notice anchor. Confirmation cannot restart the clock. |
| What constitutes an alarm for A7 | Ask Aditya; recommended distinct alert per addressed nurse, once at first screen routing, separate delivery provenance. Screen routing is not proof a person received/read it. |
| Shift schedule/timezone | Ask Aditya; configurable schedule, lab briefing uses current-run scope. No guessed hospital shift. |
| Narrative freedom | Ask Aditya; recommended structured fact-linked composition. A numeric token check cannot safely validate arbitrary prose. |
| Blind Time | Source must provide trusted/untrusted/no-data intervals and coverage; no physiology-based inference, missing coverage reported separately. |
| Alarms stopped | Require explicit versioned suppression-event definition from decision/backend owners. Neither LOOSE_SENSOR nor absence of A1 is proof a false alarm was prevented. |
| Red missing-field highlights versus alarm-only red | Emit semantic missing/error markers; Antara chooses accessible treatment without misusing alarm severity. |
| Legal text/form/version | Pin sources; distinguish human attestations, evidence and unknowns. Human owner resolves applicability; no model legal judgement. |
| Public APIs and human-edit conflict | Backend owns public routes; local labelled reference plus revision/role tests can establish the integration boundary. |

No source or dataset was altered and no teammate system was modified during this review.
