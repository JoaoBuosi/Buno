import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import check_rate_limit
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.venture_run import VentureRun
from app.models.governance import AgentTemplate, UsageSpan, now
from app.services.governance_service import policy_for, audit
from app.services.knowledge_service import snapshot_for_run
from app.schemas.venture import VentureCreate, VentureOut, VentureSummary
from app.services.access import owned_project
from app.services.venture_service import claim_run, owned_run, run_stream, utcnow

router = APIRouter()


@router.post("/projects/{project_id}/runs", response_model=VentureOut, status_code=201)
async def create_run(project_id: uuid.UUID, payload: VentureCreate, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await owned_project(db, user_id, project_id)
    check_rate_limit(f"venture-create:{user_id}", 10)
    policy = await policy_for(db, project_id)
    template = {}
    if payload.template_id:
        saved_template = (await db.execute(select(AgentTemplate).where(AgentTemplate.id == payload.template_id, AgentTemplate.user_id == user_id))).scalar_one_or_none()
        if saved_template is None:
            raise HTTPException(404, "Template não encontrado")
        template = {"id": str(saved_template.id), "name": saved_template.name, "steps": saved_template.steps}
    knowledge = await snapshot_for_run(db, user_id, project_id, payload.brief) if policy["shared_memory"] else []
    row = VentureRun(project_id=project_id, user_id=user_id, brief=payload.brief, policy_snapshot=policy,
                     template_snapshot=template, knowledge_snapshot=knowledge)
    db.add(row)
    await db.flush()
    audit(db, user_id, project_id, "run.created", "Planejamento criado com limites, template e contexto congelados.", row.id,
          {"template": template.get("id", "builtin"), "knowledge_ids": [item["id"] for item in knowledge]})
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/projects/{project_id}/runs", response_model=list[VentureSummary])
async def list_runs(project_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await owned_project(db, user_id, project_id)
    return (await db.execute(select(VentureRun).where(VentureRun.project_id == project_id, VentureRun.user_id == user_id)
        .order_by(VentureRun.created_at.desc()).limit(50))).scalars().all()


@router.get("/runs/{run_id}", response_model=VentureOut)
async def get_run(run_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await owned_run(db, user_id, run_id)


@router.post("/runs/{run_id}/stream")
async def generate_run(run_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    check_rate_limit(f"venture-run:{user_id}", 6)
    row, token = await claim_run(db, user_id, run_id)
    await db.close()
    return StreamingResponse(run_stream(row, token), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/pause", response_model=VentureOut)
async def pause_run(run_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = await owned_run(db, user_id, run_id)
    result = await db.execute(update(VentureRun).where(VentureRun.id == run_id, VentureRun.user_id == user_id,
        VentureRun.status.in_(["ready", "running", "failed"]))
        .values(status="paused", lease_token=None, lease_expires_at=None, updated_at=utcnow()))
    if result.rowcount:
        audit(db, user_id, row.project_id, "run.paused", "Execução pausada pelo usuário; etapas completas preservadas.", row.id)
    await db.commit()
    return await owned_run(db, user_id, run_id)


@router.post("/runs/{run_id}/review", response_model=VentureOut)
async def review_run(run_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = await owned_run(db, user_id, run_id)
    if row.status == "reviewed":
        return row
    result = await db.execute(update(VentureRun).where(VentureRun.id == run_id, VentureRun.user_id == user_id,
        VentureRun.status == "awaiting_review", VentureRun.next_step == 4)
        .values(status="reviewed", reviewed_at=utcnow(), updated_at=utcnow()))
    if result.rowcount != 1:
        raise HTTPException(409, "Conclua todas as etapas antes de marcar o plano como revisado")
    audit(db, user_id, row.project_id, "run.reviewed", "O usuário registrou a revisão do plano. Nenhuma ação externa foi autorizada.", row.id)
    await db.commit()
    return await owned_run(db, user_id, run_id)


@router.get("/runs/{run_id}/export")
async def export_run(run_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = await owned_run(db, user_id, run_id)
    parts = ["# Buno — planejamento do projeto", "Documento gerado por IA, sujeito a revisão humana. Nenhum código, teste ou deploy foi executado por este fluxo.", f"Estado: {row.status} | Etapas concluídas: {row.next_step}/4", "## Briefing", row.brief]
    for artifact in row.artifacts:
        parts.extend([f"## {artifact['title']}", artifact["content"]])
    return Response("\n\n".join(parts), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="buno-plano-{row.id}.md"', "Cache-Control": "no-store"})
