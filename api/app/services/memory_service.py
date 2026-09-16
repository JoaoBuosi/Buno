import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory import Memory
from app.models.user import User
from app.models.message import Message
from app.services.llm_provider import llm_provider

RELEVANT_MEMORIES_LIMIT = 5
# cosine_distance: 0 = idêntico, 2 = oposto. 0.5 é um corte razoável pra "relevante o suficiente".
MAX_RELEVANT_DISTANCE = 0.5

_EXTRACTION_INSTRUCTION = (
    "Extraia, em uma frase curta e objetiva, um fato duradouro e útil sobre o usuário "
    "a partir da troca abaixo — algo que valeria a pena lembrar em uma conversa futura "
    "(preferência, contexto pessoal, decisão tomada, projeto em andamento). "
    "Se a troca não tiver nada relevante pra lembrar depois (ex: só uma pergunta técnica "
    "pontual), responda exatamente: NADA"
)


async def maybe_store_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_message: str,
    assistant_message: str,
    source_message_id: uuid.UUID | None = None,
) -> Memory | None:
    """
    Depois de uma troca de mensagens, decide (via LLM) se algo ali merece virar
    memória de longo prazo. Se sim, gera o embedding e salva. Se não, não faz nada.
    """
    existing_user = await db.get(User, user_id)
    if existing_user is None or not existing_user.memory_enabled:
        return None
    await db.rollback()
    extracted = await _extract_memorable_fact(user_message, assistant_message)
    if extracted is None:
        return None

    embedding = await llm_provider.embed(extracted)
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if user is None or not user.memory_enabled or (source_message_id and await db.get(Message, source_message_id) is None):
        return None
    memory = Memory(
        user_id=user_id,
        content=extracted,
        embedding=embedding,
        source_message_id=source_message_id,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def _extract_memorable_fact(user_message: str, assistant_message: str) -> str | None:
    messages = [
        {"role": "system", "content": _EXTRACTION_INSTRUCTION},
        {
            "role": "user",
            "content": f"Usuário: {user_message}\nAssistente: {assistant_message}",
        },
    ]
    result = (await llm_provider.complete_chat(messages)).strip()
    if not result or result.upper().startswith("NADA"):
        return None
    return result[:600]


async def retrieve_relevant_memories(
    db: AsyncSession, user_id: uuid.UUID, query: str, limit: int = RELEVANT_MEMORIES_LIMIT
) -> list[str]:
    """
    Busca, por similaridade semântica, as memórias mais relevantes pra pergunta atual.
    É isso que dá pro Buno a sensação de "lembrar" entre conversas diferentes.
    """
    user = await db.get(User, user_id)
    if user is None or not user.memory_enabled:
        return []
    if (await db.execute(select(Memory.id).where(Memory.user_id == user_id).limit(1))).first() is None:
        return []
    await db.rollback()
    query_embedding = await llm_provider.embed(query)
    distance = Memory.embedding.cosine_distance(query_embedding)

    result = await db.execute(
        select(Memory.content, distance.label("distance"))
        .where(Memory.user_id == user_id)
        .order_by(distance)
        .limit(limit)
    )
    rows = result.all()

    return [content for content, dist in rows if dist <= MAX_RELEVANT_DISTANCE]


def _estimate_tokens(text: str) -> int:
    """
    Aproximação de contagem de tokens sem carregar o tokenizer real do Qwen
    (não vale a pena só pra isso). ~4 caracteres por token é uma média razoável
    pra português/inglês — suficiente pra ficar bem longe do limite, não pra
    ser exato.
    """
    return max(1, len(text) // 4)


def trim_history_to_token_budget(
    messages: list[dict], max_tokens: int = settings.PROVIDER_CONTEXT_TOKEN_BUDGET
) -> list[dict]:
    """Keep the latest message and newest complete history within a character budget.

    The latest message is kept whole; the system prefix takes precedence over
    older turns, and is truncated only when needed. This is an estimate, not
    the provider tokenizer's exact count.
    """
    if not messages:
        return []
    maximum = max_tokens * 4
    conversation = [dict(m) for m in messages if m["role"] != "system"]
    latest = conversation.pop() if conversation else None
    remaining = maximum - (len(latest["content"]) if latest else 0)
    if remaining < 0:
        raise ValueError("A mensagem excede o orçamento de contexto")
    systems = []
    for item in messages:
        if item["role"] == "system" and remaining:
            content = item["content"][:remaining]
            systems.append({"role": "system", "content": content})
            remaining -= len(content)
    kept = []
    for item in reversed(conversation):
        if len(item["content"]) > remaining:
            break
        kept.insert(0, item)
        remaining -= len(item["content"])
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return systems + kept + ([latest] if latest else [])
