import uuid
from datetime import datetime

from pydantic import ConfigDict, BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def non_blank(cls, value: str):
        if not value.strip():
            raise ValueError("Informe o nome do projeto")
        return value.strip()


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
