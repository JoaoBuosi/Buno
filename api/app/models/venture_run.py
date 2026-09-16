import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base_class import Base


class VentureRun(Base):
    __tablename__ = "venture_runs"
    __table_args__ = (
        CheckConstraint("next_step >= 0 AND next_step <= 4", name="ck_venture_step"),
        CheckConstraint("status IN ('ready','running','paused','failed','awaiting_review','reviewed')", name="ck_venture_status"),
        Index("ix_venture_project_created", "project_id", "created_at"),
        Index("uq_venture_user_running", "user_id", unique=True,
              postgresql_where=text("status = 'running'"), sqlite_where=text("status = 'running'")),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="ready")
    next_step: Mapped[int] = mapped_column(Integer, default=0)
    artifacts: Mapped[list[dict]] = mapped_column(JSON, default=list)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    template_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    knowledge_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_microusd: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[list] = mapped_column(JSON, default=lambda: [0, 0, 0, 0])
    governance_revision: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
