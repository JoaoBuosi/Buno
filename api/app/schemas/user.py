import uuid

from pydantic import ConfigDict, BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return value

    name: str | None = Field(default=None, max_length=120)


class UserOut(BaseModel):
    memory_enabled: bool
    id: uuid.UUID
    email: EmailStr
    name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPreferences(BaseModel):
    memory_enabled: bool
