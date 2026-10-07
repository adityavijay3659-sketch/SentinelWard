# SentinelWard foundation runbook

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

Stop the service, restore the previous application package and restart. Do not drop the
`automation` schema or LangGraph tables. Phase 1 database changes are additive so audit and
recovery evidence remains available.
