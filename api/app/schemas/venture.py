import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

RunStatus = Literal["ready", "running", "paused", "failed", "awaiting_review", "reviewed"]


class VentureCreate(BaseModel):
    brief: str = Field(min_length=20, max_length=6000)
    template_id: uuid.UUID | None = None

    @field_validator("brief")
    @classmethod
    def useful_brief(cls, value):
        value = value.strip()
        if len(value) < 20:
            raise ValueError("Descreva a ideia, o público e o problema em pelo menos 20 caracteres")
        return value


class VentureArtifact(BaseModel):
    key: str
    title: str
    content: str
    created_at: datetime


class VentureSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    status: RunStatus
    next_step: int
    error_message: str | None
    lease_expires_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VentureOut(VentureSummary):
    brief: str
    artifacts: list[VentureArtifact]
    policy_snapshot: dict
    template_snapshot: dict
    knowledge_snapshot: list[dict]
    reserved_tokens: int
    reserved_microusd: int
    attempts: list[int]
