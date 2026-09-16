import hashlib
import json
from datetime import timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.db.session import AsyncSessionLocal
from app.models.governance import AuditEvent, ProjectPolicy, UsageSpan, Approval, now
from app.models.venture_run import VentureRun
from app.schemas.governance import Policy


class BudgetExceeded(Exception):
    """A safe, user-facing refusal issued before contacting a provider."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def audit(db, user_id, project_id, kind, summary, run_id=None, details=None):
    db.add(AuditEvent(user_id=user_id, project_id=project_id, run_id=run_id, kind=kind,
                      summary=summary, details=details or {}))


async def policy_for(db, project_id):
    row = await db.get(ProjectPolicy, project_id)
    return Policy.model_validate(row.settings if row else {}).model_dump()


def estimate_reservation(prompt, output_tokens, input_microusd_per_million=0, output_microusd_per_million=0):
    # Conservative byte-based estimate, not a model tokenizer or billing invoice.
    inputs = sum(len(item["content"].encode("utf-8")) + 128 for item in prompt) + 256
    if min(input_microusd_per_million, output_microusd_per_million) < 0:
        raise ValueError("Rates cannot be negative")
    cost = (inputs * input_microusd_per_million + output_tokens * output_microusd_per_million + 999999) // 1000000
    return inputs + output_tokens, cost


async def reserve_step(run_id, lease_token, step, role, prompt, model, *, input_rate=0, output_rate=0):
    async with AsyncSessionLocal() as db:
        row = await db.get(VentureRun, run_id)
        if row is None or row.lease_token != lease_token or row.status != "running":
            raise BudgetExceeded("A execução foi pausada ou substituída.")
        policy = Policy.model_validate(row.policy_snapshot or {}).model_dump()
        tokens, cost = estimate_reservation(prompt, policy["output_tokens"], input_rate, output_rate)
        attempts = list(row.attempts)
        reason = None
        if attempts[step] >= policy["attempts_per_step"]:
            reason = "Esta etapa atingiu o limite de tentativas deste planejamento."
        elif tokens > policy["step_tokens"] or row.reserved_tokens + tokens > policy["run_tokens"]:
            reason = "O limite de tokens deste planejamento não comporta outra etapa."
        elif cost > policy["step_budget_microusd"] or row.reserved_microusd + cost > policy["run_budget_microusd"]:
            reason = "O limite financeiro deste planejamento não comporta outra etapa."
        if reason:
            audit(db, row.user_id, row.project_id, "budget.blocked", reason, row.id)
            await db.commit()
            raise BudgetExceeded(reason + " Revise os limites antes de criar um novo planejamento.")
        attempts[step] += 1
        result = await db.execute(update(VentureRun).where(VentureRun.id == run_id, VentureRun.lease_token == lease_token,
                VentureRun.status == "running", VentureRun.governance_revision == row.governance_revision)
            .values(reserved_tokens=row.reserved_tokens + tokens, reserved_microusd=row.reserved_microusd + cost,
                    attempts=attempts, governance_revision=row.governance_revision + 1))
        if result.rowcount != 1:
            await db.rollback()
            raise BudgetExceeded("Outra execução alterou este planejamento. Atualize a página.")
        span = UsageSpan(user_id=row.user_id, project_id=row.project_id, run_id=row.id, lease_token=lease_token,
            step=step, role=role, template_key=str(row.template_snapshot.get("id", "builtin")), model=model,
            attempt=attempts[step], reserved_tokens=tokens, reserved_microusd=cost, prompt_hash=digest(prompt),
            prompt=prompt if policy["trace_content"] else None)
        db.add(span)
        audit(db, row.user_id, row.project_id, "stage.started", f"Etapa {step + 1}: {role}. Consumo reservado antes da chamada.",
              row.id, {"tokens_reserved": tokens, "attempt": attempts[step], "template": span.template_key})
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise BudgetExceeded("Esta chamada já foi reservada ou o projeto foi alterado. Atualize a página.") from None
        return span.id, policy


async def settle_in_transaction(db, span_id, status, duration_ms, meter, response=""):
    if span_id is None:
        return
    row = await db.get(UsageSpan, span_id)
    if row is None:
        return
    result = await db.execute(update(UsageSpan).where(UsageSpan.id == span_id, UsageSpan.status == "reserved")
        .values(status=status, duration_ms=max(0, duration_ms), input_tokens=meter.input_tokens if meter else None,
                output_tokens=meter.output_tokens if meter else None, ended_at=now(),
                response=response[:32000] if row.prompt is not None else None))
    if result.rowcount:
        labels = {"succeeded": "concluída", "failed": "falhou", "interrupted": "interrompida"}
        audit(db, row.user_id, row.project_id, f"stage.{status}", f"Etapa {row.step + 1} encerrada: {labels.get(status, status)}.", row.run_id,
              {"span_id": str(row.id), "duration_ms": max(0, duration_ms)})


async def settle_span(span_id, status, duration_ms, meter, response=""):
    if span_id is None:
        return
    async with AsyncSessionLocal() as db:
        await settle_in_transaction(db, span_id, status, duration_ms, meter, response)
        # Reservations are deliberately not refunded: crashes/partial responses have unknown use.
        await db.commit()


async def scoped_row(db, model, user_id, project_id, object_id):
    row = (await db.execute(select(model).where(model.id == object_id, model.user_id == user_id, model.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Recurso não encontrado")
    return row


async def consume_approval(db, user_id, project_id, approval_id, action, target, payload):
    """Internal tool gateway: caller must use this in the action transaction/outbox.

    No executable cloud adapter is registered in this release. Never expose this as
    a browser endpoint or consume an approval before persisting an execution intent.
    """
    expected = digest({"project": str(project_id), "action": action, "target": target, "payload": payload})
    result = await db.execute(update(Approval).where(Approval.id == approval_id, Approval.user_id == user_id,
        Approval.project_id == project_id, Approval.digest == expected, Approval.status == "approved", Approval.expires_at > now())
        .values(status="consumed").execution_options(synchronize_session="fetch"))
    if result.rowcount != 1:
        raise HTTPException(409, "A ação não tem uma aprovação válida para estes parâmetros")
    audit(db, user_id, project_id, "approval.consumed", "Autorização vinculada à ação consumida uma única vez.", details={"approval_id": str(approval_id), "digest": expected})


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
