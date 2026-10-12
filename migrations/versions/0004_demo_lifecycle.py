"""Separate durable demo runtime; resets never delete audit history."""

from alembic import op

revision = "0004_demo_lifecycle"
down_revision = "0003_phase3_m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE automation.demo_m6_runtime (
            singleton_id integer PRIMARY KEY CHECK(singleton_id=1),
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Keep demo lifecycle history; roll back the application only")
