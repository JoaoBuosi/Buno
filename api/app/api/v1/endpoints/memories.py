import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.memory import Memory

router = APIRouter()


@router.get("")
async def list_memories(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Memory).where(Memory.user_id == user_id).order_by(Memory.created_at.desc()))).scalars().all()
    return [{"id": str(m.id), "content": m.content, "created_at": m.created_at} for m in rows]


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Memória não encontrada")
    await db.delete(row)
    await db.commit()
