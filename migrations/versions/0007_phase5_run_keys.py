"""Retain repeated entity keys independently in every demo run."""

from alembic import op

revision = "0007_phase5_run_keys"
down_revision = "0006_phase5_narratives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE automation.phase5_items DROP CONSTRAINT phase5_items_pkey;
        ALTER TABLE automation.phase5_items ADD PRIMARY KEY(run_id,kind,item_id);
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve per-run history; roll back the application only")
