import asyncio
import base64
from dataclasses import asdict
from datetime import timedelta
import json
import os
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from app.core.config import settings
from app.models.governance import Approval, VaultSecret, UsageSpan, KnowledgeNote, now
from app.models.venture_run import VentureRun
from app.schemas.governance import Policy
from app.services import governance_service as gs, venture_service as vs, vault_service as vault
from app.services.llm_provider import llm_provider, LLMProvider
from app.services.call_meter import metered_call, current_meter
from app.vault_setup import initialize
from tests.conftest import PASSWORD

BRIEF = "Criar um MVP de agenda para salões pequenos, com orçamento local e sem nuvem."
SECRET = "test-only-sensitive-material-do-not-print"


async def project(env, headers=None):
    return (await env.client.post("/projects", headers=headers or env.a, json={"name": "Governança"})).json()["id"]


def path(pid, route):
    return f"/governance/projects/{pid}/{route}"


async def plan(env, pid, **extra):
    response = await env.client.post(f"/venture/projects/{pid}/runs", headers=env.a, json={"brief": BRIEF, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def dashboard(env, pid):
    result = await env.client.get(path(pid, "dashboard"), headers=env.a)
    assert result.status_code == 200, result.text
    return result.json()


async def configure(env, pid, **overrides):
    config = {**Policy().model_dump(), **overrides}
    response = await env.client.put(path(pid, "policy"), headers=env.a, json=config)
    assert response.status_code == 200, response.text
    return response.json()


async def execute(env, run):
    response = await env.client.post(f"/venture/runs/{run['id']}/stream", headers=env.a)
    assert response.status_code == 200, response.text
    return response


def setup_vault(env, monkeypatch):
    key_path = env.tmp / "secrets" / "vault.key"
    initialize(key_path)
    monkeypatch.setattr(settings, "VAULT_KEY_FILE", str(key_path))
    return key_path


async def secret(env, pid, value=SECRET):
    response = await env.client.post(path(pid, "secrets"), headers=env.a,
        json={"name": "Credencial de teste", "kind": "api_key", "value": value,
              "allowed_roles": ["implementation"], "allowed_tools": ["api.read"]})
    assert response.status_code == 201, response.text
    return response


async def approval(env, pid):
    response = await env.client.post(path(pid, "approvals"), headers=env.a,
        json={"action": "production_deploy", "target": "projeto-prod", "rationale": "Publicar a revisão que passou nos testes externos.",
              "payload": {"resource": "aplicativo", "revision": "commit-123", "estimated_microusd": 250000}})
    assert response.status_code == 201, response.text
    return response.json()


async def note(env, pid, content="A agenda precisa operar sem acesso à nuvem."):
    response = await env.client.post(path(pid, "notes"), headers=env.a,
        json={"title": "Decisão de arquitetura", "content": content, "kind": "decision"})
    assert response.status_code == 201, response.text
    return response.json()


async def test_project_isolation_on_all_governance_routes(env, monkeypatch):
    pid = await project(env)
    setup_vault(env, monkeypatch)
    sid = (await secret(env, pid)).json()["id"]
    nid = (await note(env, pid))["id"]
    aid = (await approval(env, pid))["id"]
    run = await plan(env, pid)
    valid_action = {"action": "paid_resource", "target": "target", "rationale": "Teste de isolamento por conta", "payload": {"resource": "vm", "revision": "1", "estimated_microusd": 1}}
    calls = [("GET", "dashboard", None), ("GET", "audit", None), ("PUT", "policy", Policy().model_dump()),
        ("DELETE", f"secrets/{sid}", None), ("GET", f"spans/{uuid.uuid4()}", None),
        ("POST", "approvals", valid_action), ("POST", f"approvals/{aid}/decision", {"decision": "approved", "digest": "0"*64, "password": PASSWORD}),
        ("POST", "notes", {"title": "Invadir", "content": "Dados privados", "kind": "fact"}), ("DELETE", f"notes/{nid}", None),
        ("POST", "edges", {"source_id": nid, "target_id": nid, "relation": "supports"}), ("DELETE", f"edges/{uuid.uuid4()}", None),
        ("POST", f"knowledge/from-run/{run['id']}", None), ("PUT", f"ratings/{run['id']}", {"score": 5}),
        ("POST", "secrets", {"name": "foreign", "kind": "api_key", "value": "x", "allowed_roles": ["product"], "allowed_tools": ["api.read"]})]
    for method, route, body in calls:
        response = await env.client.request(method, path(pid, route), headers=env.b, **({"json": body} if body else {}))
        assert response.status_code == 404, (method, route, response.text)
    assert (await env.client.get(path(pid, "dashboard"))).status_code == 401


async def test_limits_block_before_provider_and_are_frozen(env):
    pid = await project(env)
    await configure(env, pid, run_tokens=1000, step_tokens=1000, output_tokens=64)
    run = await plan(env, pid)
    await configure(env, pid)
    response = await execute(env, run)
    assert "limite de tokens" in response.text and env.prompts == []
    saved = (await env.client.get(f"/venture/runs/{run['id']}", headers=env.a)).json()
    assert saved["policy_snapshot"]["run_tokens"] == 1000 and saved["artifacts"] == []
    assert any(event["kind"] == "budget.blocked" for event in (await dashboard(env, pid))["events"])


async def test_retry_cap_and_nonrefundable_reservation(env, monkeypatch):
    pid = await project(env)
    await configure(env, pid, attempts_per_step=1)
    run = await plan(env, pid)
    calls = 0
    async def broken(messages):
        nonlocal calls
        calls += 1
        yield "rascunho"
        raise RuntimeError("private-error")
    monkeypatch.setattr(llm_provider, "stream_chat", broken)
    await execute(env, run)
    first = (await env.client.get(f"/venture/runs/{run['id']}", headers=env.a)).json()
    assert first["reserved_tokens"] > 0 and first["attempts"] == [1, 0, 0, 0]
    second = await execute(env, run)
    assert "limite de tentativas" in second.text and calls == 1
    assert (await env.client.get(f"/venture/runs/{run['id']}", headers=env.a)).json()["reserved_tokens"] == first["reserved_tokens"]


async def test_financial_limit_prevents_paid_reservation(env):
    pid = await project(env)
    run = await plan(env, pid)
    async with env.factory() as db:
        row, token = await vs.claim_run(db, env.aid, uuid.UUID(run["id"]))
    with pytest.raises(gs.BudgetExceeded, match="financeiro"):
        await gs.reserve_step(row.id, token, 0, "product", [{"content": "teste", "role": "user"}], "simulated-paid", input_rate=1000000, output_rate=1000000)
    async with env.factory() as db:
        saved = await db.get(VentureRun, row.id)
        assert saved.reserved_microusd == 0 and saved.attempts == [0, 0, 0, 0]


async def test_invalid_limits_and_unknown_fields_rejected(env):
    pid = await project(env)
    for extra in [{"attempts_per_step": 999}, {"run_budget_microusd": -1}, {"step_budget_microusd": 5}, {"disable_approval": True}, {"step_tokens": 1000}]:
        assert (await env.client.put(path(pid, "policy"), headers=env.a, json={**Policy().model_dump(), **extra})).status_code == 422


async def test_vault_ciphertext_permissions_and_revocation(env, monkeypatch):
    pid = await project(env)
    setup_vault(env, monkeypatch)
    response = await secret(env, pid)
    sid = uuid.UUID(response.json()["id"])
    assert SECRET not in response.text
    async with env.factory() as db:
        row = await db.get(VaultSecret, sid)
        assert SECRET not in row.ciphertext
        assert await vault.resolve_for_tool(db, env.aid, uuid.UUID(pid), sid, "implementation", "api.read") == SECRET
        await db.commit()
    for actor, role, tool, status in [(env.bid, "implementation", "api.read", 404), (env.aid, "review", "api.read", 403), (env.aid, "implementation", "production.deploy", 403)]:
        async with env.factory() as db:
            with pytest.raises(HTTPException) as error:
                await vault.resolve_for_tool(db, actor, uuid.UUID(pid), sid, role, tool)
            assert error.value.status_code == status
    assert SECRET not in json.dumps(await dashboard(env, pid))
    assert (await env.client.delete(path(pid, f"secrets/{sid}"), headers=env.a)).status_code == 204
    async with env.factory() as db:
        assert (await db.get(VaultSecret, sid)).ciphertext == ""
        with pytest.raises(HTTPException) as error:
            await vault.resolve_for_tool(db, env.aid, uuid.UUID(pid), sid, "implementation", "api.read")
        assert error.value.status_code == 403


async def test_vault_binds_ciphertext_to_identity_and_detects_tampering(env, monkeypatch):
    pid = await project(env)
    setup_vault(env, monkeypatch)
    first, second = (await secret(env, pid)).json(), (await secret(env, pid)).json()
    async with env.factory() as db:
        one, two = await db.get(VaultSecret, uuid.UUID(first["id"])), await db.get(VaultSecret, uuid.UUID(second["id"]))
        assert one.ciphertext != two.ciphertext
        two.ciphertext = one.ciphertext
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await vault.resolve_for_tool(db, env.aid, uuid.UUID(pid), two.id, "implementation", "api.read")
        assert error.value.status_code == 503


async def test_vault_unconfigured_and_validation_errors_do_not_echo_secrets(env, monkeypatch):
    pid = await project(env)
    monkeypatch.setattr(settings, "VAULT_KEY_FILE", str(env.tmp / "missing"))
    payload = {"name": "private", "kind": "api_key", "value": SECRET, "allowed_roles": ["product"], "allowed_tools": ["api.read"]}
    response = await env.client.post(path(pid, "secrets"), headers=env.a, json=payload)
    assert response.status_code == 503 and SECRET not in response.text
    payload["value"] = SECRET * 1000
    invalid = await env.client.post(path(pid, "secrets"), headers=env.a, json=payload)
    assert invalid.status_code == 422 and SECRET not in invalid.text
    assert (await dashboard(env, pid))["vault_ready"] is False


def test_vault_setup_preserves_existing_key_and_permissions(tmp_path):
    target = tmp_path / "secure" / "vault.key"
    assert initialize(target)
    original = target.read_bytes()
    assert len(base64.b64decode(original)) == 32
    assert not initialize(target) and target.read_bytes() == original
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


async def test_approval_requires_password_exact_digest_and_single_use(env):
    pid = await project(env)
    action = await approval(env, pid)
    url = path(pid, f"approvals/{action['id']}/decision")
    payload = {"decision": "approved", "digest": action["digest"], "password": "wrong"}
    assert (await env.client.post(url, headers=env.a, json=payload)).status_code == 403
    payload.update(password=PASSWORD, digest="0"*64)
    assert (await env.client.post(url, headers=env.a, json=payload)).status_code == 409
    payload["digest"] = action["digest"]
    assert (await env.client.post(url, headers=env.a, json=payload)).json()["status"] == "approved"
    assert (await env.client.post(url, headers=env.a, json=payload)).status_code == 409
    async with env.factory() as db:
        with pytest.raises(HTTPException):
            await gs.consume_approval(db, env.aid, uuid.UUID(pid), uuid.UUID(action["id"]), action["action"], action["target"], {**action["payload"], "revision": "changed"})
        await db.rollback()
        await gs.consume_approval(db, env.aid, uuid.UUID(pid), uuid.UUID(action["id"]), action["action"], action["target"], action["payload"])
        await db.commit()
        with pytest.raises(HTTPException):
            await gs.consume_approval(db, env.aid, uuid.UUID(pid), uuid.UUID(action["id"]), action["action"], action["target"], action["payload"])
    assert (await dashboard(env, pid))["external_execution_enabled"] is False


@pytest.mark.parametrize("state", ["pending", "rejected", "expired"])
async def test_approval_gate_rejects_unapproved_actions(env, state):
    pid = await project(env)
    action = await approval(env, pid)
    async with env.factory() as db:
        row = await db.get(Approval, uuid.UUID(action["id"]))
        if state == "expired":
            row.status = "approved"; row.expires_at = now() - timedelta(seconds=1)
        else:
            row.status = state
        await db.commit()
        with pytest.raises(HTTPException):
            await gs.consume_approval(db, env.aid, uuid.UUID(pid), row.id, row.action, row.target, row.payload)
    if state == "expired":
        assert (await dashboard(env, pid))["approvals"][0]["status"] == "expired"


async def test_project_memory_reuse_freezes_context_and_deduplicates(env, monkeypatch):
    pid = await project(env)
    calls = 0
    async def embed(text):
        nonlocal calls
        calls += 1
        return [1.0] + [0.0] * (settings.EMBEDDING_DIMENSIONS - 1)
    monkeypatch.setattr(llm_provider, "embed", embed)
    first = await note(env, pid)
    assert (await note(env, pid))["id"] == first["id"] and calls == 1
    run = await plan(env, pid)
    assert len(run["knowledge_snapshot"]) == 1 and calls == 2
    assert (await env.client.delete(path(pid, f"notes/{first['id']}"), headers=env.a)).status_code == 204
    await execute(env, run)
    assert calls == 2
    assert all("A agenda precisa operar" in prompt[1]["content"] for prompt in env.prompts)
    assert (await dashboard(env, pid))["notes"] == []


async def test_memory_fallback_and_cross_project_edges(env):
    pid, other = await project(env), await project(env)
    first = await note(env, pid)
    second = await note(env, pid, "O prazo inicial será de duas semanas.")
    foreign = await note(env, other)
    assert not first["indexed"]
    response = await env.client.post(path(pid, "edges"), headers=env.a, json={"source_id": first["id"], "target_id": foreign["id"], "relation": "supports"})
    assert response.status_code == 404
    payload = {"source_id": first["id"], "target_id": second["id"], "relation": "depends_on"}
    assert (await env.client.post(path(pid, "edges"), headers=env.a, json=payload)).status_code == 201
    assert (await env.client.post(path(pid, "edges"), headers=env.a, json=payload)).status_code == 409
    await env.client.delete(path(pid, f"notes/{first['id']}"), headers=env.a)
    assert (await dashboard(env, pid))["edges"] == []
    await configure(env, pid, shared_memory=False)
    assert (await plan(env, pid))["knowledge_snapshot"] == []


async def test_templates_private_reusable_and_immutable_snapshots(env):
    pid, other = await project(env), await project(env)
    payload = {"name": "Meu time", "description": "Teste", "steps": [asdict(step) for step in vs.STEPS]}
    payload["steps"][0]["instruction"] = "Organize produto sem nuvem, usando o requisito especial ALFA-XYZ."
    created = (await env.client.post("/governance/templates", headers=env.a, json=payload)).json()
    assert (await env.client.get("/governance/templates", headers=env.b)).json()["items"] == []
    assert (await env.client.post("/governance/templates", headers=env.b, json={**payload, "source_id": created["id"]})).status_code == 404
    run = await plan(env, pid, template_id=created["id"])
    another = await plan(env, other, template_id=created["id"])
    assert run["template_snapshot"] == another["template_snapshot"]
    await execute(env, run)
    assert "ALFA-XYZ" in env.prompts[0][0]["content"]
    bad = {**payload, "steps": list(reversed(payload["steps"]))}
    assert (await env.client.post("/governance/templates", headers=env.a, json=bad)).status_code == 422


@pytest.mark.parametrize("record", [False, True])
async def test_trace_opt_in_and_audit_are_durable_and_owned(env, record):
    pid = await project(env)
    await configure(env, pid, trace_content=record)
    run = await plan(env, pid)
    await execute(env, run)
    panel = await dashboard(env, pid)
    assert len(panel["spans"]) == 4 and all(span["status"] == "succeeded" for span in panel["spans"])
    span = panel["spans"][0]
    detail = (await env.client.get(path(pid, f"spans/{span['id']}"), headers=env.a)).json()
    assert detail["content_recorded"] is record
    assert bool(detail["prompt"]) is record and bool(detail["response"]) is record
    assert (await env.client.get(path(pid, f"spans/{span['id']}"), headers=env.b)).status_code == 404
    assert len([event for event in panel["events"] if event["kind"] == "stage.succeeded"]) == 4
    assert all(span["input_tokens"] is None for span in panel["spans"])
    assert panel["metrics"][0]["efficiency_score"] is None


async def test_reviewed_plans_can_be_shared_and_scored(env):
    pid = await project(env)
    run = await plan(env, pid)
    rating = path(pid, f"ratings/{run['id']}")
    sharing = path(pid, f"knowledge/from-run/{run['id']}")
    assert (await env.client.put(rating, headers=env.a, json={"score": 5})).status_code == 409
    assert (await env.client.post(sharing, headers=env.a)).status_code == 409
    await execute(env, run)
    await env.client.post(f"/venture/runs/{run['id']}/review", headers=env.a)
    assert (await env.client.put(rating, headers=env.a, json={"score": 4})).status_code == 200
    assert (await env.client.put(rating, headers=env.a, json={"score": 5})).status_code == 200
    assert (await env.client.post(sharing, headers=env.a)).status_code == 200
    report = (await dashboard(env, pid))["metrics"][0]
    assert report["rated_runs"] == 1 and report["quality_mean"] == 5
    assert 0 < report["efficiency_score"] <= 100


async def test_ollama_meter_limits_output_and_records_reported_tokens(monkeypatch):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["options"]["num_predict"] == 123
        return httpx.Response(200, text=json.dumps({"message": {"content": "sim"}, "done": True, "prompt_eval_count": 21, "eval_count": 2}))
    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    with metered_call(123) as meter:
        assert "".join([part async for part in LLMProvider().stream_chat([{"role": "user", "content": "Oi"}])]) == "sim"
        assert meter.input_tokens == 21 and meter.output_tokens == 2
    assert current_meter.get() is None


async def test_cancelled_step_keeps_reservation_and_closes_trace(env, monkeypatch):
    pid = await project(env)
    run = await plan(env, pid)
    async with env.factory() as db:
        row, token = await vs.claim_run(db, env.aid, uuid.UUID(run["id"]))
    stream = vs.run_stream(row, token)
    await anext(stream); await anext(stream); await anext(stream)
    await stream.aclose()
    report = await dashboard(env, pid)
    assert report["spans"][0]["status"] == "interrupted"
    assert report["spans"][0]["reserved_tokens"] > 0


async def test_audit_pagination_has_no_overlap(env):
    pid = await project(env)
    async with env.factory() as db:
        for i in range(65):
            gs.audit(db, env.aid, uuid.UUID(pid), "test", f"Evento {i}")
        await db.commit()
    first = (await dashboard(env, pid))["events"]
    second = (await env.client.get(path(pid, f"audit?before={first[-1]['id']}"), headers=env.a)).json()
    assert len(first) == 50 and len(second) == 15
    assert not ({event["id"] for event in first} & {event["id"] for event in second})
