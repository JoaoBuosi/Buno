import uuid
from datetime import datetime, timezone
from app.services.access import owned_project, owned_conversation

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import ConversationMoveToProject, ConversationOut, MessageOut, ConversationCreate, ConversationRename

router = APIRouter()


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """
    Cria uma conversa vazia (sem mensagens ainda). Usado quando o usuário anexa
    um arquivo ANTES de mandar a primeira mensagem — precisamos de um
    conversation_id pra associar o documento a ela.
    """
    project_id = payload.project_id if payload else None
    if project_id:
        await owned_project(db, user_id, project_id)
    conversation = Conversation(user_id=user_id, title="Nova conversa", project_id=project_id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    """
    Lista as conversas do usuário logado, mais recentes primeiro. Se
    `project_id` for passado, filtra só as conversas daquele projeto.
    """
    query = select(Conversation).where(Conversation.user_id == user_id)
    if project_id is not None:
        query = query.where(Conversation.project_id == project_id)

    result = await db.execute(query.order_by(Conversation.updated_at.desc()))
    return result.scalars().all()


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[Message]:
    """Histórico completo de uma conversa, em ordem cronológica."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.patch("/{conversation_id}/project", response_model=ConversationOut)
async def move_conversation_to_project(
    conversation_id: uuid.UUID,
    payload: ConversationMoveToProject,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """Move uma conversa existente pra dentro de um projeto (ou tira, se project_id=None)."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada")

    if payload.project_id:
        await owned_project(db, user_id, payload.project_id)
    conversation.project_id = payload.project_id
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada")

    await db.delete(conversation)
    await db.commit()


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(conversation_id: uuid.UUID, payload: ConversationRename,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    conversation = await owned_conversation(db, user_id, conversation_id)
    conversation.title = payload.title
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return conversation
