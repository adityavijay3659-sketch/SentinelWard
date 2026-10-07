"""Create Phase 1 automation foundation tables."""

from alembic import op

revision = "0001_phase1_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS automation")
    op.execute(
        """
        CREATE TABLE automation.ingress_events (
            ingress_id uuid PRIMARY KEY,
            topic text NOT NULL,
            received_at timestamptz NOT NULL,
            payload jsonb NOT NULL,
            payload_sha256 char(64) NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            correlation_id text NOT NULL,
            status text NOT NULL CHECK (status IN ('accepted', 'processed', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.dead_letters (
            dead_letter_id uuid PRIMARY KEY,
            topic text NOT NULL,
            received_at timestamptz NOT NULL,
            payload_sha256 char(64) NOT NULL,
            payload_excerpt text NOT NULL,
            error_code text NOT NULL,
            error_detail text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.workflow_runs (
            thread_id text PRIMARY KEY,
            correlation_id text NOT NULL,
            terminal_status text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.action_reservations (
            action_id text PRIMARY KEY,
            action_key text NOT NULL UNIQUE,
            correlation_id text NOT NULL,
            agent_id text NOT NULL,
            action_name text NOT NULL,
            target_id text NOT NULL,
            status text NOT NULL CHECK (
                status IN ('reserved', 'completed', 'rejected', 'failed', 'unknown')
            ),
            request jsonb NOT NULL,
            result jsonb,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.audit_events (
            audit_id uuid PRIMARY KEY,
            occurred_at timestamptz NOT NULL,
            correlation_id text NOT NULL,
            event_type text NOT NULL,
            actor text NOT NULL,
            detail jsonb NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.outbox_events (
            outbox_id uuid PRIMARY KEY,
            delivery_key text NOT NULL UNIQUE,
            destination text NOT NULL,
            payload jsonb NOT NULL,
            correlation_id text NOT NULL,
            status text NOT NULL CHECK (status IN ('pending', 'delivered', 'failed', 'unknown')),
            attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_attempt_at timestamptz NOT NULL,
            last_error text,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE automation.undo_links (
            undo_action_id text PRIMARY KEY,
            original_action_id text NOT NULL UNIQUE,
            approved_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ingress_correlation_idx ON automation.ingress_events (correlation_id)")
    op.execute(
        "CREATE INDEX audit_correlation_idx "
        "ON automation.audit_events (correlation_id, occurred_at)"
    )
    op.execute(
        "CREATE INDEX outbox_pending_idx ON automation.outbox_events (status, next_attempt_at)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Phase 1 schema is intentionally irreversible; roll back the application only"
    )
