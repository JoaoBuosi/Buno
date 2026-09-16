"""Persist bounded Venture Builder workflows and their artifacts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("venture_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("next_step", sa.Integer(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("next_step >= 0 AND next_step <= 4", name="ck_venture_step"),
        sa.CheckConstraint("status IN ('ready','running','paused','failed','awaiting_review','reviewed')", name="ck_venture_status"),
    )
    op.create_index("ix_venture_project_created", "venture_runs", ["project_id", "created_at"])
    op.create_index("uq_venture_user_running", "venture_runs", ["user_id"], unique=True, postgresql_where=sa.text("status = 'running'"))


def downgrade():
    op.drop_table("venture_runs")
