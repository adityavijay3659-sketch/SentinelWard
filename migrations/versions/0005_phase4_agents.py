"""Durable isolated agent lifecycle and effect recovery."""

from alembic import op

revision = "0005_phase4_agents"
down_revision = "0004_demo_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE automation.phase4_runtime (
            singleton_id integer PRIMARY KEY CHECK (singleton_id=1),
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve agent audit/history; roll back the application only")
