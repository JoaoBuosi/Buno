import uuid
from datetime import datetime

from pydantic import ConfigDict, BaseModel


class DocumentOut(BaseModel):
    processing_note: str | None = None
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    text_extracted: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentAttach(BaseModel):
    conversation_id: uuid.UUID
