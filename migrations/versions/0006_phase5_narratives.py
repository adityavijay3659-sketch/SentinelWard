"""Normalized run-scoped report, workload, fact and generation records."""

from alembic import op

revision = "0006_phase5_narratives"
down_revision = "0005_phase4_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE automation.phase5_runtime (
            singleton_id integer PRIMARY KEY CHECK(singleton_id=1), state jsonb NOT NULL
        );
        CREATE TABLE automation.phase5_items (
            kind text NOT NULL, item_id text NOT NULL, run_id text NOT NULL,
            body jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(kind,item_id)
        );
        CREATE INDEX phase5_run_kind ON automation.phase5_items(run_id,kind);
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve report attestations and audit; roll back the application only")
