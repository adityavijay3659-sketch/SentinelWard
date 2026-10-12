# Phase 4 isolated lab and verification

Use Python `D:\SentinelWard-Phase2-Venv\Scripts\python.exe`. The lab operates on loopback and uses no Windows service, Docker or WSL. Generated credentials and artifacts stay outside Git.

## Prepare

1. Extract the official Windows x64 Mosquitto 2.0.22 distribution into a private lab directory. The verified installer SHA-256 is `2d3d57d918cc8cd4a0df6c6812edf1c3d723ee813b569354ff4a021e9e1d84bc`.
2. Start the broker using the tool below. It generates Dynamic Security accounts, deny-by-default ACLs, runtime config and credentials. Do not point this tool at a team broker.
3. Start the existing embedded PostgreSQL server and create a new dedicated test database. Apply migrations through 0005 and initialize the checkpointer.

```powershell
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B tools\phase4_lab.py start --root 'C:\Users\Aditya\SentinelWard-Phase4-Lab\run1' --broker-bin 'C:\Users\Aditya\SentinelWard-Phase4-Lab\mosquitto'
$env:SENTINEL_DATABASE_URL='postgresql://postgres@127.0.0.1:5432/sentinel_phase4_20261012'
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m sentinelward db upgrade
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m sentinelward db init-checkpointer
```

The default broker port is 18883. A2 admin can use only Dynamic Security control topics. Cleanup has no application-topic ACL. Backend publishes only control/requests; decision producer only verdicts; simulator devices only their assigned vitals. The observer publishes agent outputs and the test session topic. The session-test subscription is a lab-only permission and must not be copied into a production device ACL.

## Run all checks

```powershell
$env:SENTINEL_TEST_DATABASE_URL=$env:SENTINEL_DATABASE_URL
$env:SENTINEL_TEST_PHASE4_CONFIG='C:\Users\Aditya\SentinelWard-Phase4-Lab\run1\runtime.json'
$env:SENTINEL_TEST_VITALDB_ROOT='D:\SentinelWard-Data\VitalDB\m6-20261009-run1'
$env:LANGGRAPH_STRICT_MSGPACK='true'
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m ruff check .
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m ruff format --check .
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m mypy --strict src
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B -m pytest -q
```

CI equivalents remain `uv sync --frozen --extra dev`, Ruff lint/format, `uv run mypy`, migration/checkpointer commands and `uv run pytest --cov=sentinelward --cov-report=term-missing`. Real-broker tests explicitly skip without the isolated lab config; that skip must not be treated as evidence of real broker validation. Optional research/data skips in ordinary CI remain separately identified.

## Run the isolated service

Set test environment, loopback HTTP host, local broker host/port/observer credentials, M6/demo enabled, an explicit demo M6 context file, Phase 4 runtime config and a private backend service token. Then run `python -B -m sentinelward validate-config` and `python -B -m sentinelward serve`.

Required additional settings:

```text
SENTINEL_ENVIRONMENT=test
SENTINEL_HTTP_HOST=127.0.0.1
SENTINEL_MQTT_HOST=127.0.0.1
SENTINEL_MQTT_PORT=18883
SENTINEL_MQTT_TLS=false
SENTINEL_MQTT_USERNAME=p4-observer
SENTINEL_MQTT_PASSWORD=<from the local private credentials file>
SENTINEL_BACKEND_SERVICE_TOKEN=<private local token>
SENTINEL_M6_ENABLED=true
SENTINEL_DEMO_LIFECYCLE_ENABLED=true
SENTINEL_M6_CONTEXTS_FILE=<private demo context file matching the inventory>
SENTINEL_PHASE4_CONFIG_FILE=C:\Users\Aditya\SentinelWard-Phase4-Lab\run1\runtime.json
```

The isolated profile uses actual persisted A1 screen alerts and a fixture roster. Telegram is explicitly unavailable; failed backup delivery cannot close the screen alert. This profile is not a hospital or deployed-team service.

## Stop and preserve evidence

Stop `serve`, then run the broker stop command. It checks that the stored PID still belongs to the expected lab executable before terminating it. Remove only the dedicated test database and stop only the PostgreSQL process started for this verification. Keep JSON/XML results, hashes, broker logs and evidence artifacts for the handoff.

```powershell
& 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe' -B tools\phase4_lab.py stop --root 'C:\Users\Aditya\SentinelWard-Phase4-Lab\run1'
```

Reset preserves historical DB rows and evidence. A new valid local run restores harness-owned accounts; it does not authorize reconnection of production devices. Never put credentials, raw recordings, generated evidence or broker binaries in a commit.
