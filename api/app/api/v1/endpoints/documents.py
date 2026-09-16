import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.access import owned_conversation
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import DocumentAttach, DocumentOut
from app.services.document_service import save_and_process_document

router = APIRouter()

MAX_UPLOAD_SIZE_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    conversation_id: uuid.UUID | None = Form(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Document:
    if conversation_id:
        await owned_conversation(db, user_id, conversation_id)
    data = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(422, "O arquivo está vazio")
    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Arquivo maior que o limite de {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    return await save_and_process_document(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        filename=file.filename or "arquivo",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.conversation_id == conversation_id, Document.user_id == user_id)
        .order_by(Document.created_at.asc())
    )
    return result.scalars().all()


@router.patch("/{document_id}/attach", response_model=DocumentOut)
async def attach_document_to_conversation(
    document_id: uuid.UUID,
    payload: DocumentAttach,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Document:
    """
    Liga um documento (enviado antes de a conversa existir, numa conversa nova)
    à conversa que acabou de ser criada. Sem isso, o arquivo fica "órfão" e
    nunca aparece como contexto pro chat.
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado")

    await owned_conversation(db, user_id, payload.conversation_id)
    document.conversation_id = payload.conversation_id
    await db.commit()
    await db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado")

    Path(document.storage_path).unlink(missing_ok=True)
    Path(document.storage_path).with_suffix(".txt").unlink(missing_ok=True)
    await db.delete(document)
    await db.commit()
