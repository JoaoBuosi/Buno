"""CRUD, provisionamento e auditoria dos agentes do usuário."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user_id
from app.db.session import AsyncSessionLocal, get_db
from app.models.agent import Agent, AgentActivity
from app.schemas.agent import AgentActivityOut, AgentCreate, AgentOut, AgentUpdate
from app.services.foundry_provider import (
    FoundryProviderError,
    FoundryProvisionResult,
    provision_agent,
)

router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def activity(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    kind: str,
    summary: str,
    details: dict | None = None,
) -> AgentActivity:
    return AgentActivity(
        user_id=user_id,
        agent_id=agent_id,
        kind=kind,
        summary=summary,
        details=details or {},
    )


async def get_owned_agent(
    db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente não encontrado")
    return agent


async def _provision_agent_background(agent_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Provisiona fora da sessão HTTP e atualiza o card quando terminar."""
    async with AsyncSessionLocal() as read_db:
        result = await read_db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.status == "paused":
            return
        name, model, instructions = agent.name, agent.model, agent.instructions

    try:
        provisioned = await provision_agent(name, model, instructions)
    except Exception as exc:
        # FoundryProviderError já remove detalhes sensíveis; exceções inesperadas
        # ficam genéricas para não vazar URLs, headers ou credenciais nos logs da UI.
        safe_error = str(exc) if isinstance(exc, FoundryProviderError) else (
            "Não foi possível provisionar o agente no Azure. Confira a configuração do Foundry."
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
            )
            current = result.scalar_one_or_none()
            if current is None or current.status == "paused":
                return
            current.status = "error"
            current.status_message = "Erro ao provisionar no Azure."
            current.last_error = safe_error[:500]
            current.updated_at = utcnow()
            db.add(
                activity(
                    user_id,
                    agent_id,
                    "provisioning_failed",
                    "O provisionamento no Azure falhou.",
                    {"provider": "foundry", "error": safe_error[:500]},
                )
            )
            await db.commit()
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
        )
        current = result.scalar_one_or_none()
        if current is None or current.status == "paused":
            return
        current.status = "active"
        current.status_message = (
            f"Agente disponível no Foundry (versão {provisioned.agent_version})."
        )
        current.foundry_agent_id = provisioned.agent_id or None
        current.foundry_agent_version = provisioned.agent_version or None
        current.last_error = None
        current.updated_at = utcnow()
        db.add(
            activity(
                user_id,
                agent_id,
                "provisioned",
                "Agente provisionado no Microsoft Foundry.",
                {
                    "provider": "foundry",
                    "agent_id": provisioned.agent_id,
                    "version": provisioned.agent_version,
                },
            )
        )
        await db.commit()


@router.get("", response_model=list[AgentOut])
async def list_agents(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[Agent]:
    result = await db.execute(
        select(Agent).where(Agent.user_id == user_id).order_by(Agent.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    provider = payload.provider
    model = payload.model.strip() or "qwen3.5:9b"
    provisioning = provider == "foundry"
    agent = Agent(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
        profile=payload.profile,
        model=model,
        provider=provider,
        status="provisioning" if provisioning else "active",
        status_message="Provisionando no Azure…" if provisioning else "Agente local disponível.",
    )
    db.add(agent)
    await db.flush()
    db.add(
        activity(
            user_id,
            agent.id,
            "created",
            "Agente criado.",
            {"provider": provider, "model": model},
        )
    )
    await db.commit()
    await db.refresh(agent)
    if provisioning:
        background_tasks.add_task(_provision_agent_background, agent.id, user_id)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    return await get_owned_agent(db, user_id, agent_id)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await get_owned_agent(db, user_id, agent_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return agent
    for field, value in changes.items():
        setattr(agent, field, value)
    agent.updated_at = utcnow()
    needs_provision = agent.provider == "foundry" and agent.status != "paused"
    if needs_provision:
        agent.status = "provisioning"
        agent.status_message = "Atualização sendo provisionada no Azure…"
        agent.last_error = None
    elif agent.status != "paused":
        agent.status = "active"
        agent.status_message = "Agente local disponível."
    db.add(
        activity(
            user_id,
            agent.id,
            "updated",
            "Instruções ou configuração do agente atualizadas.",
            {"fields": sorted(changes)},
        )
    )
    await db.commit()
    await db.refresh(agent)
    if needs_provision:
        background_tasks.add_task(_provision_agent_background, agent.id, user_id)
    return agent


@router.post("/{agent_id}/pause", response_model=AgentOut)
async def pause_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await get_owned_agent(db, user_id, agent_id)
    agent.status = "paused"
    agent.status_message = "Agente pausado pelo usuário."
    agent.paused_at = utcnow()
    agent.updated_at = utcnow()
    db.add(activity(user_id, agent.id, "paused", "Agente pausado pelo usuário."))
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/resume", response_model=AgentOut)
async def resume_agent(
    agent_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await get_owned_agent(db, user_id, agent_id)
    provisioning = agent.provider == "foundry"
    agent.status = "provisioning" if provisioning else "active"
    agent.status_message = "Provisionando no Azure…" if provisioning else "Agente local disponível."
    agent.paused_at = None
    agent.last_error = None
    agent.updated_at = utcnow()
    db.add(activity(user_id, agent.id, "resumed", "Agente retomado pelo usuário."))
    await db.commit()
    await db.refresh(agent)
    if provisioning:
        background_tasks.add_task(_provision_agent_background, agent.id, user_id)
    return agent


@router.get("/{agent_id}/logs", response_model=list[AgentActivityOut])
async def list_agent_logs(
    agent_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[AgentActivity]:
    await get_owned_agent(db, user_id, agent_id)
    result = await db.execute(
        select(AgentActivity)
        .where(AgentActivity.agent_id == agent_id, AgentActivity.user_id == user_id)
        .order_by(AgentActivity.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    agent = await get_owned_agent(db, user_id, agent_id)
    await db.delete(agent)
    await db.commit()
