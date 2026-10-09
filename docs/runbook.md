# SentinelWard foundation runbook

## Phase 2 live alert configuration

Phase 2 live effects require the existing MQTT/PostgreSQL/backend values plus:

```text
SENTINEL_EXTERNAL_EFFECT_MODE=live
SENTINEL_TELEGRAM_BOT_TOKEN=<secret>
SENTINEL_TELEGRAM_RECIPIENTS_FILE=/etc/sentinelward/telegram-recipients.json
SENTINEL_ALERT_DEMO_SECONDS=30
SENTINEL_ALERT_DESIGN_REAL_SECONDS=60
```

The recipient file is not part of the repository. It must be owned by the service account with
mode `0600` and contain canonical staff IDs mapped to Telegram integer chat IDs:

```json
{
  "staff:priya": 123456789,
  "staff:ravi": 987654321,
  "staff:doctor1": 555555555
}
```

Run `sentinelward db upgrade` with the migration role before starting the runtime role. The
service uses one Uvicorn worker because it also owns the single Telegram poller and APScheduler
leader. Live startup fails closed if the backend, bot token or recipient file is missing.

## Install

Use Python 3.12. On LinuxONE, install the Psycopg C build prerequisites before synchronization;
the project selects `psycopg[c]` on s390x and a binary wheel on development machines.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install uv
uv sync --frozen
```

Copy `.env.example` to `/etc/sentinelward/sentinelward.env`, replace every placeholder and set
mode `0600`. Never place this file in the repository.

## Initialize

Run with the migration role:

```bash
sentinelward validate-config
sentinelward db upgrade
sentinelward db init-checkpointer
```

Both database commands are safe to repeat. The application migration is additive and its
downgrade intentionally preserves audit history.

The wheel packages its Alembic migration scripts. A release check must install the wheel into a
fresh virtual environment and run `sentinelward db upgrade` against a new empty database; testing
only from a source checkout is insufficient.

## Operate

```bash
sudo cp deploy/sentinelward.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sentinelward
curl --fail http://127.0.0.1:8088/health/live
curl --fail http://127.0.0.1:8088/health/ready
curl --fail http://127.0.0.1:8088/metrics
```

Read logs through `journalctl -u sentinelward`. Search using `correlation_id`; do not copy secrets
or raw clinical data into tickets.

## Failure response

- Readiness reports PostgreSQL false: stop new mutation testing and restore database access.
- MQTT false: verify DNS, port, CA, client certificate/credentials and broker ACLs.
- Backend false: retain events in the outbox and verify service authentication.
- Action status unknown: reconcile with the target system; do not blindly repeat it.
- Malformed input: use the dead-letter error code and payload hash to contact the producer.

## Rollback

For M6 research setup, replay and evaluation commands, follow
[Phase 3 implementation](phase-3-implementation.md). M6 is disabled by default.
The `design-real` profile rejects research M6 until its real-data safety gate is
reviewed; TLS and the existing alert workflow remain enforced. Silence on the
QoS 0 vitals stream requires the backend's freshness monitoring; M6 cannot infer
missing messages while no new frames arrive.

Stop the service, restore the previous application package and restart. Do not drop the
`automation` schema or LangGraph tables. Phase 1 database changes are additive so audit and
recovery evidence remains available.
