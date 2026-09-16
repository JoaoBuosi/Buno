import uuid
from dataclasses import asdict
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id, verify_password
from app.core.rate_limit import check_rate_limit
from app.db.session import get_db
from app.models.user import User
from app.models.venture_run import VentureRun
from app.models.governance import (ProjectPolicy, AuditEvent, UsageSpan, Approval, VaultSecret,
    KnowledgeNote, KnowledgeEdge, AgentTemplate, RunRating, now)
from app.schemas.governance import (Policy, SecretCreate, ApprovalCreate, ApprovalDecision, NoteCreate,
    EdgeCreate, TemplateCreate, RatingCreate)
from app.services.access import owned_project
from app.services.governance_service import policy_for, audit, digest, scoped_row, aware
from app.services.knowledge_service import add_note
from app.services.vault_service import encrypt, vault_ready
from app.services.venture_service import STEPS
from app.services.foundry_provider import foundry_status

router = APIRouter()


async def scope(project_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await owned_project(db, user_id, project_id)
    return db, user_id, project_id


def fields(row, *names):
    return {key: getattr(row, key) for key in names}


def secret_view(row):
    return fields(row, "id", "name", "kind", "allowed_roles", "allowed_tools", "revoked_at", "created_at")


def note_view(row):
    return {**fields(row, "id", "title", "content", "kind", "digest", "source_run_id", "created_at"), "indexed": row.embedding is not None}


def approval_view(row):
    value = fields(row, "id", "action", "target", "payload", "rationale", "digest", "status", "expires_at", "decided_at", "created_at")
    if row.status in {"pending", "approved"} and aware(row.expires_at) <= now():
        value["status"] = "expired"
    return value


async def project_rows(db, model, user_id, project_id, limit=100):
    return (await db.execute(select(model).where(model.user_id == user_id, model.project_id == project_id)
        .order_by(model.created_at.desc()).limit(limit))).scalars().all()


async def metrics(db, user_id, project_id):
    # All spans, not just the dashboard's newest page. No content is needed here.
    groups = (await db.execute(select(UsageSpan.template_key, UsageSpan.status, func.count(),
        func.sum(UsageSpan.reserved_tokens), func.sum(UsageSpan.input_tokens), func.sum(UsageSpan.output_tokens),
        func.sum(UsageSpan.reserved_microusd), func.sum(UsageSpan.duration_ms))
        .where(UsageSpan.user_id == user_id, UsageSpan.project_id == project_id)
        .group_by(UsageSpan.template_key, UsageSpan.status))).all()
    ratings = (await db.execute(select(VentureRun.template_snapshot, RunRating.score).join(RunRating, RunRating.run_id == VentureRun.id)
        .where(VentureRun.user_id == user_id, VentureRun.project_id == project_id))).all()
    result = {}
    for key, status, count, tokens, inputs, outputs, cost, duration in groups:
        item = result.setdefault(key, {"template_key": key, "calls": 0, "succeeded": 0, "tokens_reserved": 0,
            "input_tokens_reported": 0, "output_tokens_reported": 0, "estimated_microusd": 0, "duration_ms": 0,
            "ratings": [], "efficiency_score": None})
        item["calls"] += count
        item["succeeded"] += count if status == "succeeded" else 0
        item["tokens_reserved"] += tokens or 0
        item["input_tokens_reported"] += inputs or 0
        item["output_tokens_reported"] += outputs or 0
        item["estimated_microusd"] += cost or 0
        item["duration_ms"] += duration or 0
    for snapshot, score in ratings:
        key = str(snapshot.get("id", "builtin"))
        if key in result:
            result[key]["ratings"].append(score)
    for item in result.values():
        scores = item.pop("ratings")
        item["rated_runs"] = len(scores)
        item["quality_mean"] = round(sum(scores) / len(scores), 2) if scores else None
        item["success_rate"] = round(item["succeeded"] / item["calls"], 4)
        if scores:
            item["efficiency_score"] = round(100 * (sum(scores) / len(scores) / 5) * item["success_rate"] /
                (1 + item["tokens_reserved"] / item["calls"] / 10000), 2)
    return list(result.values())


@router.get("/projects/{project_id}/dashboard")
async def dashboard(access=Depends(scope)):
    db, user_id, project_id = access
    spans = await project_rows(db, UsageSpan, user_id, project_id, 50)
    events = (await db.execute(select(AuditEvent).where(AuditEvent.user_id == user_id, AuditEvent.project_id == project_id)
                              .order_by(AuditEvent.id.desc()).limit(50))).scalars().all()
    foundry = foundry_status()
    return {"policy": await policy_for(db, project_id), "vault_ready": vault_ready(),
        "provider": "foundry" if foundry["enabled"] else "ollama",
        "external_execution_enabled": bool(foundry["enabled"] and foundry["configured"]),
        "foundry": foundry,
        "secrets": [secret_view(row) for row in await project_rows(db, VaultSecret, user_id, project_id)],
        "approvals": [approval_view(row) for row in await project_rows(db, Approval, user_id, project_id)],
        "notes": [note_view(row) for row in await project_rows(db, KnowledgeNote, user_id, project_id, 200)],
        "edges": [fields(row, "id", "source_id", "target_id", "relation") for row in await project_rows(db, KnowledgeEdge, user_id, project_id, 500)],
        "spans": [fields(row, "id", "run_id", "step", "role", "template_key", "model", "attempt", "status", "reserved_tokens",
                         "input_tokens", "output_tokens", "reserved_microusd", "duration_ms", "created_at", "ended_at") for row in spans],
        "events": [fields(row, "id", "run_id", "kind", "summary", "details", "created_at") for row in events],
        "metrics": await metrics(db, user_id, project_id)}


@router.get("/projects/{project_id}/audit")
async def audit_page(before: int | None = Query(default=None, ge=1), access=Depends(scope)):
    db, user_id, project_id = access
    query = select(AuditEvent).where(AuditEvent.user_id == user_id, AuditEvent.project_id == project_id)
    if before:
        query = query.where(AuditEvent.id < before)
    rows = (await db.execute(query.order_by(AuditEvent.id.desc()).limit(50))).scalars().all()
    return [fields(row, "id", "run_id", "kind", "summary", "details", "created_at") for row in rows]


@router.get("/projects/{project_id}/spans/{span_id}")
async def trace_detail(span_id: uuid.UUID, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, UsageSpan, user_id, project_id, span_id)
    return {**fields(row, "id", "run_id", "role", "status", "prompt_hash", "prompt", "response"), "content_recorded": row.prompt is not None}


@router.put("/projects/{project_id}/policy")
async def set_policy(payload: Policy, access=Depends(scope)):
    db, user_id, project_id = access
    row = await db.get(ProjectPolicy, project_id)
    if row:
        row.settings = payload.model_dump(); row.updated_at = now()
    else:
        db.add(ProjectPolicy(project_id=project_id, settings=payload.model_dump()))
    audit(db, user_id, project_id, "policy.changed", "Limites alterados para novos planejamentos.", details=payload.model_dump())
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "A configuração foi alterada em outro acesso. Atualize e tente novamente.") from None
    return payload


@router.post("/projects/{project_id}/secrets", status_code=201)
async def create_secret(payload: SecretCreate, access=Depends(scope)):
    db, user_id, project_id = access
    check_rate_limit(f"vault-write:{user_id}", 10)
    secret_id = uuid.uuid4()
    ciphertext, key_id = encrypt(payload.value.get_secret_value(), user_id, project_id, secret_id)
    row = VaultSecret(id=secret_id, user_id=user_id, project_id=project_id, name=payload.name, kind=payload.kind,
        ciphertext=ciphertext, key_id=key_id, allowed_roles=payload.allowed_roles, allowed_tools=payload.allowed_tools)
    db.add(row)
    audit(db, user_id, project_id, "vault.created", "Credencial cifrada adicionada ao cofre.", details={"secret_id": str(secret_id), "kind": payload.kind})
    await db.commit()
    return secret_view(row)


@router.delete("/projects/{project_id}/secrets/{secret_id}", status_code=204)
async def revoke_secret(secret_id: uuid.UUID, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, VaultSecret, user_id, project_id, secret_id)
    if not row.revoked_at:
        row.ciphertext = ""; row.revoked_at = now()
        audit(db, user_id, project_id, "vault.revoked", "Credencial revogada e conteúdo cifrado removido do registro ativo.", details={"secret_id": str(secret_id)})
        await db.commit()


@router.post("/projects/{project_id}/approvals", status_code=201)
async def request_approval(payload: ApprovalCreate, access=Depends(scope)):
    db, user_id, project_id = access
    check_rate_limit(f"approval-create:{user_id}", 10)
    content = payload.payload.model_dump()
    row = Approval(user_id=user_id, project_id=project_id, action=payload.action, target=payload.target,
        payload=content, rationale=payload.rationale, expires_at=now() + timedelta(hours=24),
        digest=digest({"project": str(project_id), "action": payload.action, "target": payload.target, "payload": content}))
    db.add(row)
    await db.flush()
    audit(db, user_id, project_id, "approval.requested", "Ação aguardando autorização expressa; execução externa não conectada.",
          details={"approval_id": str(row.id), "digest": row.digest, "action": row.action})
    await db.commit()
    return approval_view(row)


@router.post("/projects/{project_id}/approvals/{approval_id}/decision")
async def decide_approval(approval_id: uuid.UUID, payload: ApprovalDecision, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, Approval, user_id, project_id, approval_id)
    check_rate_limit(f"approval-decision:{user_id}", 5)
    user = await db.get(User, user_id)
    if not verify_password(payload.password.get_secret_value(), user.hashed_password):
        raise HTTPException(403, "Senha incorreta; a decisão não foi registrada")
    result = await db.execute(update(Approval).where(Approval.id == row.id, Approval.status == "pending",
        Approval.digest == payload.digest, Approval.expires_at > now()).values(status=payload.decision, decided_at=now())
        .execution_options(synchronize_session="fetch"))
    if result.rowcount != 1:
        raise HTTPException(409, "Solicitação expirada, alterada ou já decidida. Atualize a página.")
    audit(db, user_id, project_id, f"approval.{payload.decision}", "Decisão expressa registrada para a ação especificada.",
          details={"approval_id": str(row.id), "digest": row.digest})
    await db.commit()
    return approval_view(row)


@router.post("/projects/{project_id}/notes", status_code=201)
async def create_note(payload: NoteCreate, access=Depends(scope)):
    db, user_id, project_id = access
    check_rate_limit(f"knowledge:{user_id}", 20)
    return note_view(await add_note(db, user_id, project_id, payload.title, payload.content, payload.kind))


@router.delete("/projects/{project_id}/notes/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, KnowledgeNote, user_id, project_id, note_id)
    await db.delete(row)
    audit(db, user_id, project_id, "knowledge.deleted", "Registro compartilhado removido. Cópias de contexto de execuções anteriores permanecem.", details={"note_id": str(note_id)})
    await db.commit()


@router.post("/projects/{project_id}/knowledge/from-run/{run_id}")
async def publish_run(run_id: uuid.UUID, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, VentureRun, user_id, project_id, run_id)
    if row.status != "reviewed":
        raise HTTPException(409, "Revise o plano antes de publicá-lo na memória compartilhada")
    results = []
    for item in row.artifacts:
        note = await add_note(db, user_id, project_id, item["title"], item["content"][:6000], "artifact", row.id)
        results.append(note_view(note))
    return results


@router.post("/projects/{project_id}/edges", status_code=201)
async def create_edge(payload: EdgeCreate, access=Depends(scope)):
    db, user_id, project_id = access
    for object_id in [payload.source_id, payload.target_id]:
        await scoped_row(db, KnowledgeNote, user_id, project_id, object_id)
    if payload.source_id == payload.target_id:
        raise HTTPException(422, "Escolha dois registros diferentes")
    row = KnowledgeEdge(user_id=user_id, project_id=project_id, **payload.model_dump())
    db.add(row)
    audit(db, user_id, project_id, "knowledge.linked", "Relação de conhecimento registrada.", details={"source": str(payload.source_id), "target": str(payload.target_id), "relation": payload.relation})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Esta relação já existe ou o registro foi removido") from None
    return fields(row, "id", "source_id", "target_id", "relation")


@router.delete("/projects/{project_id}/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: uuid.UUID, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, KnowledgeEdge, user_id, project_id, edge_id)
    await db.delete(row)
    audit(db, user_id, project_id, "knowledge.unlinked", "Relação de conhecimento removida.", details={"edge_id": str(edge_id)})
    await db.commit()


@router.get("/templates")
async def templates(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AgentTemplate).where(AgentTemplate.user_id == user_id).order_by(AgentTemplate.created_at.desc()).limit(100))).scalars().all()
    return {"builtin": {"id": "builtin", "name": "Planejamento Buno", "description": "Quatro papéis de planejamento", "steps": [asdict(step) for step in STEPS]},
            "items": [fields(row, "id", "name", "description", "steps", "source_id", "created_at") for row in rows]}


@router.post("/templates", status_code=201)
async def save_template(payload: TemplateCreate, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    check_rate_limit(f"template:{user_id}", 10)
    if payload.source_id:
        source = await db.get(AgentTemplate, payload.source_id)
        if source is None or source.user_id != user_id:
            raise HTTPException(404, "Template de origem não encontrado")
    count = (await db.execute(select(func.count()).select_from(AgentTemplate).where(AgentTemplate.user_id == user_id))).scalar_one()
    if count >= 100:
        raise HTTPException(409, "Sua biblioteca chegou ao limite de 100 templates")
    row = AgentTemplate(user_id=user_id, **payload.model_dump())
    db.add(row); await db.commit()
    return fields(row, "id", "name", "description", "steps", "source_id", "created_at")


@router.put("/projects/{project_id}/ratings/{run_id}")
async def rate_run(run_id: uuid.UUID, payload: RatingCreate, access=Depends(scope)):
    db, user_id, project_id = access
    row = await scoped_row(db, VentureRun, user_id, project_id, run_id)
    if row.status != "reviewed":
        raise HTTPException(409, "Revise o planejamento antes de avaliar a utilidade")
    rating = (await db.execute(select(RunRating).where(RunRating.run_id == run_id))).scalar_one_or_none()
    if rating:
        rating.score = payload.score
    else:
        db.add(RunRating(user_id=user_id, project_id=project_id, run_id=run_id, score=payload.score))
    audit(db, user_id, project_id, "run.rated", "Avaliação de utilidade registrada pelo usuário.", run_id, {"score": payload.score})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Avaliação alterada em outro acesso. Tente novamente.") from None
    return {"score": payload.score}
