"""Bounded M6 episode state; scores share the durable MQTT outbox."""

from alembic import op

revision = "0003_phase3_m6"
down_revision = "0002_phase2_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE automation.m6_states (
            bed_id text PRIMARY KEY,
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    raise RuntimeError("M6 state is retained for recovery; roll back the application only")
