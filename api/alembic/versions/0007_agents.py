"""User agent registry and activity logs."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("profile", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("status_message", sa.String(length=500), nullable=True),
        sa.Column("foundry_agent_id", sa.String(length=255), nullable=True),
        sa.Column("foundry_agent_version", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','provisioning','error','paused')", name="ck_agent_status"),
        sa.CheckConstraint("provider IN ('ollama','foundry')", name="ck_agent_provider"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agents_user_id", "agents", ["user_id"], unique=False)
    op.create_index("ix_agents_user_updated", "agents", ["user_id", "updated_at"], unique=False)
    op.create_table(
        "agent_activity",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_activity_user_id", "agent_activity", ["user_id"], unique=False)
    op.create_index("ix_agent_activity_agent_id", "agent_activity", ["agent_id"], unique=False)
    op.create_index("ix_agent_activity_agent_created", "agent_activity", ["agent_id", "created_at"], unique=False)


def downgrade():
    op.drop_index("ix_agent_activity_agent_created", table_name="agent_activity")
    op.drop_index("ix_agent_activity_agent_id", table_name="agent_activity")
    op.drop_index("ix_agent_activity_user_id", table_name="agent_activity")
    op.drop_table("agent_activity")
    op.drop_index("ix_agents_user_updated", table_name="agents")
    op.drop_index("ix_agents_user_id", table_name="agents")
    op.drop_table("agents")
