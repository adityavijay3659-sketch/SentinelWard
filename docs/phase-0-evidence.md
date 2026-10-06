# Phase 0 verification evidence

Verified: 7 October 2026. All executable toys live outside this repository under `C:\Users\Aditya\sentinelward-phase0-toys`; dependencies, database files and models live under `D:\SentinelWard-Phase0-Lab`.

## Isolated environment

- Python 3.12.14
- LangGraph 1.2.14
- LangGraph PostgreSQL checkpointer 3.1.2
- APScheduler 3.11.3
- psycopg 3.3.6
- SQLAlchemy 2.1.3
- paho-mqtt 2.1.0
- python-telegram-bot 22.8
- River 0.26.1
- VitalDB 1.7.2
- PostgreSQL test binary 17.10, bound to `127.0.0.1:55432`
- llama.cpp b11433, commit `50569eb87`

These versions prove local feasibility. They are not the final LinuxONE lockfile; LinuxONE must test and pin its own compatible set.

## Results

| Check | Result | Evidence |
|---|---|---|
| LangGraph human pause | pass | first process printed `PAUSED_AND_PERSISTED` |
| LangGraph recovery | pass | second process printed `RESUMED_FROM_POSTGRES_AND_COMPLETED` |
| Persistent timer | pass | scheduled job survived shutdown and printed `RESTORED_JOB_FIRED_EXACTLY_ONCE` |
| Page-Hinkley | pass | no stable-period alarm; gradual shift detected at sample index 94 |
| VitalDB track discovery | pass | 3,024 cases contained the complete requested ART/NIBP track set |
| VitalDB sample read | pass | case 1 loaded 11,543 one-second rows with 347 finite NIBP MAP samples |
| Telegram contract | pass offline | callback payload was within 64 bytes and the same message ID was edited |
| Granite local inference | pass | model followed the exact-response toy instruction through `llama-cli` |

## Granite artifact used for the toy

- Model: IBM `granite-3.3-2b-instruct-Q3_K_S.gguf`
- Size: 1,130,296,608 bytes
- SHA-256: `CA71C0FAAEA5647C6F34BB55D8AE9516E94828E0065CDBBF4680348BE2BBBFD3`
- Location: D: lab only; the model is intentionally excluded from Git.

## Tests that remain external

- Live Telegram delivery/edit requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; neither exists in the current environment.
- LinuxONE compatibility requires access to the actual VM and cannot be inferred from Windows.
- Team contract confirmations remain with the named owners in the checklist.

No result above claims production readiness or validates a clinical model. These are tool-learning and feasibility checks only.
