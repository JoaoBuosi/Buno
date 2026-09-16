import uuid
from datetime import datetime

from pydantic import ConfigDict, BaseModel, Field, field_validator

from app.models.message import MessageRole


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationMoveToProject(BaseModel):
    project_id: uuid.UUID | None  # None = tira a conversa do projeto (fica solta)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    project_id: uuid.UUID | None = None


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def non_blank(cls, value: str):
        if not value.strip():
            raise ValueError("O título não pode estar vazio")
        return value.strip()
