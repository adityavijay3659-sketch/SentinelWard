"""Create Phase 2 A1 alert state tables."""

from alembic import op

revision = "0002_phase2_alerts"
down_revision = "0001_phase1_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE automation.alerts (
            alert_id text PRIMARY KEY,
            bed_id text NOT NULL,
            active boolean NOT NULL,
            state jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX one_active_alert_per_bed ON automation.alerts (bed_id) WHERE active"
    )
    op.execute(
        """
        CREATE TABLE automation.alert_callbacks (
            event_id text PRIMARY KEY,
            alert_id text NOT NULL REFERENCES automation.alerts(alert_id),
            received_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.alert_callback_tokens (
            token text PRIMARY KEY,
            alert_id text NOT NULL REFERENCES automation.alerts(alert_id),
            action text NOT NULL CHECK (
                action IN ('ack', 'escalate', 'patient_ok', 'patient_not_ok')
            ),
            target jsonb NOT NULL,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.alert_deliveries (
            delivery_key text PRIMARY KEY,
            alert_id text NOT NULL REFERENCES automation.alerts(alert_id),
            staff_id text NOT NULL,
            status text NOT NULL CHECK (status IN ('pending', 'delivered', 'failed')),
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX alert_delivery_status_idx ON automation.alert_deliveries (status, updated_at)"
    )
    op.execute(
        """
        CREATE TABLE automation.roster_snapshots (
            bed_id text PRIMARY KEY,
            assignment_version text NOT NULL,
            valid_until timestamptz NOT NULL,
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.apscheduler_jobs (
            id varchar(191) PRIMARY KEY,
            next_run_time double precision,
            job_state bytea NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_automation_apscheduler_jobs_next_run_time "
        "ON automation.apscheduler_jobs (next_run_time)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Phase 2 schema is intentionally irreversible; roll back the application only"
    )
