import asyncio
import math
import re
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.models.governance import KnowledgeNote
from app.services.llm_provider import llm_provider
from app.services.governance_service import audit, digest


async def optional_embedding(text):
    try:
        async with asyncio.timeout(settings.KNOWLEDGE_EMBED_TIMEOUT):
            vector = await llm_provider.embed(text)
        if len(vector) != settings.EMBEDDING_DIMENSIONS or not all(math.isfinite(x) for x in vector):
            return None
        if not any(vector):
            return None
        return vector
    except Exception:
        return None


async def add_note(db, user_id, project_id, title, content, kind, source_run_id=None):
    fingerprint = digest({"content": content, "kind": kind})
    existing = (await db.execute(select(KnowledgeNote).where(KnowledgeNote.project_id == project_id,
                        KnowledgeNote.user_id == user_id, KnowledgeNote.digest == fingerprint))).scalar_one_or_none()
    if existing:
        return existing
    count = (await db.execute(select(func.count()).select_from(KnowledgeNote).where(KnowledgeNote.project_id == project_id))).scalar_one()
    if count >= 200:
        raise HTTPException(409, "Este projeto chegou ao limite de 200 registros de conhecimento")
    embedding = await optional_embedding(content)
    row = KnowledgeNote(user_id=user_id, project_id=project_id, title=title, content=content, kind=kind,
        digest=fingerprint, embedding=embedding, embedding_model=settings.PROVIDER_EMBEDDING_MODEL if embedding else None,
        source_run_id=source_run_id)
    db.add(row)
    audit(db, user_id, project_id, "knowledge.created", "Conhecimento adicionado ao projeto.", source_run_id,
          {"kind": kind, "digest": fingerprint, "indexed": embedding is not None})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(select(KnowledgeNote).where(KnowledgeNote.project_id == project_id,
                    KnowledgeNote.user_id == user_id, KnowledgeNote.digest == fingerprint))).scalar_one_or_none()
        if existing:
            return existing
        raise HTTPException(409, "O projeto foi alterado durante o salvamento") from None
    return row


async def snapshot_for_run(db, user_id, project_id, brief):
    rows = (await db.execute(select(KnowledgeNote).where(KnowledgeNote.user_id == user_id,
                            KnowledgeNote.project_id == project_id).order_by(KnowledgeNote.created_at.desc()).limit(200))).scalars().all()
    if not rows:
        return []
    query = await optional_embedding(brief) if any(row.embedding_model == settings.PROVIDER_EMBEDDING_MODEL for row in rows) else None
    words = set(re.findall(r"\w{3,}", brief.lower()))
    def score(row):
        if query is not None and row.embedding is not None and row.embedding_model == settings.PROVIDER_EMBEDDING_MODEL:
            values = row.embedding
            denominator = math.sqrt(sum(x*x for x in query) * sum(float(x)*float(x) for x in values))
            return sum(a * float(b) for a, b in zip(query, values)) / denominator if denominator else 0
        found = set(re.findall(r"\w{3,}", (row.title + " " + row.content).lower()))
        return len(words & found) / max(1, len(words))
    chosen = sorted(rows, key=score, reverse=True)[:4]
    # Freeze small excerpts once. Resuming never re-embeds or substitutes project facts.
    return [{"id": str(row.id), "title": row.title, "content": row.content[:650], "digest": row.digest,
             "truncated": len(row.content) > 650} for row in chosen]
