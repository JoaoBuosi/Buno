import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Profile = Literal["developer", "marketing", "data", "finance", "product", "custom"]
Provider = Literal["ollama", "foundry"]


def clean_text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} não pode estar vazio")
    return value


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(min_length=20, max_length=12000)
    profile: Profile = "custom"
    model: str = Field(default="", max_length=120)
    provider: Provider = "ollama"

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return clean_text(value, "O nome")

    @field_validator("description", "instructions", "model")
    @classmethod
    def valid_text(cls, value: str, info) -> str:
        if info.field_name == "description":
            return value.strip()
        return clean_text(value, info.field_name)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=20, max_length=12000)
    profile: Profile | None = None
    model: str | None = Field(default=None, max_length=120)

    @field_validator("name", "instructions", "model")
    @classmethod
    def valid_text(cls, value: str | None, info) -> str | None:
        return None if value is None else clean_text(value, info.field_name)

    @field_validator("description")
    @classmethod
    def valid_description(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    instructions: str
    profile: Profile
    model: str
    provider: Provider
    status: Literal["active", "provisioning", "error", "paused"]
    status_message: str | None
    foundry_agent_id: str | None
    foundry_agent_version: str | None
    last_error: str | None
    paused_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentActivityOut(BaseModel):
    id: int
    kind: str
    summary: str
    details: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
