"""User-controlled cross-conversation memory.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("processing_note", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("documents", "processing_note")
    op.drop_column("users", "memory_enabled")
