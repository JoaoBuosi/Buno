"""Project-scoped controls. Secret values never appear in API response schemas."""
import uuid
from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.config import settings
from app.db.base_class import Base


def now():
    return datetime.now(timezone.utc)


class Scoped:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectPolicy(Base):
    __tablename__ = "project_policies"
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("venture_runs.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsageSpan(Scoped, Base):
    __tablename__ = "usage_spans"
    __table_args__ = (UniqueConstraint("run_id", "lease_token", "step", name="uq_span_execution_step"),)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("venture_runs.id", ondelete="CASCADE"), index=True)
    lease_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    step: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(80))
    template_key: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(255))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="reserved")
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    reserved_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[list | None] = mapped_column(JSON, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Scoped, Base):
    __tablename__ = "action_approvals"
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(250))
    payload: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VaultSecret(Scoped, Base):
    __tablename__ = "vault_secrets"
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    ciphertext: Mapped[str] = mapped_column(Text)
    key_id: Mapped[str] = mapped_column(String(32))
    allowed_roles: Mapped[list] = mapped_column(JSON)
    allowed_tools: Mapped[list] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeNote(Scoped, Base):
    __tablename__ = "knowledge_notes"
    __table_args__ = (UniqueConstraint("project_id", "digest", name="uq_project_note_digest"),)
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    digest: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list | None] = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("venture_runs.id", ondelete="SET NULL"), nullable=True)


class KnowledgeEdge(Scoped, Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation", name="uq_knowledge_edge"),)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_notes.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_notes.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(30))


class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500))
    steps: Mapped[list] = mapped_column(JSON)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RunRating(Scoped, Base):
    __tablename__ = "run_ratings"
    __table_args__ = (UniqueConstraint("run_id", name="uq_run_rating"),)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("venture_runs.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer)
