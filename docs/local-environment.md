# Local environment inventory

Checked: 7 October 2026. This is an observation record, not the LinuxONE runtime specification.

| Capability | Local status |
|---|---|
| Git | available: 2.52.0.windows.1 |
| Python | available: 3.14.3 |
| pip | available: 25.3 |
| PostgreSQL | disposable 17.10 test server under `D:\SentinelWard-Phase0-Lab`, loopback only |
| Docker | not available on PATH |
| `llama-cli` | b11433 installed under the isolated D: lab |
| Isolated Python | 3.12.14 under the D: lab |
| LangGraph | 1.2.14 in the isolated environment |
| LangGraph PostgreSQL checkpointer | 3.1.2 in the isolated environment |
| APScheduler | 3.11.3 in the isolated environment |
| paho-mqtt | 2.1.0 in the isolated environment |
| python-telegram-bot | 22.8 in the isolated environment |
| River | 0.26.1 in the isolated environment |
| VitalDB Python package | 1.7.2 in the isolated environment |

## Consequences

- No project dependency was installed into the global Python 3.14 environment.
- The local toy lab uses isolated Python 3.12.14; LinuxONE must still confirm its supported version.
- Treat Python 3.11 or 3.12 as the preferred compatibility target until LinuxONE is inspected; record the final choice after testing rather than assuming it.
- PostgreSQL-backed restart, offline Telegram contract, Granite, VitalDB and Page-Hinkley toy tests passed; see the evidence file.
- Docker is not required by the selected runtime design and must not become a hidden dependency.

The lab is disposable and outside the repository. A system copy of 7-Zip was installed only to unpack the lightweight PostgreSQL test binary. No PostgreSQL Windows service was installed.
