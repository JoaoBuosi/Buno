import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.project import Project


async def owned_conversation(db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID):
    row = (await db.execute(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Conversa não encontrada")
    return row


async def owned_project(db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID):
    row = (await db.execute(select(Project).where(
        Project.id == project_id, Project.user_id == user_id
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Projeto não encontrado")
    return row
