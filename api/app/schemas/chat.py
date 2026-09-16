import uuid

from pydantic import BaseModel, Field, field_validator
from app.core.config import settings


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=settings.MAX_MESSAGE_CHARS)

    @field_validator("message")
    @classmethod
    def non_blank(cls, value: str):
        if not value.strip():
            raise ValueError("Escreva uma mensagem antes de enviar")
        return value

    conversation_id: uuid.UUID | None = None  # None = cria uma conversa nova
    # só é usado quando conversation_id é None — nasce a conversa já dentro do projeto
    project_id: uuid.UUID | None = None
    # Quando informado, substitui uma mensagem do usuário e remove as respostas
    # posteriores antes de gerar novamente (editar e reenviar).
    edit_message_id: uuid.UUID | None = None
 
