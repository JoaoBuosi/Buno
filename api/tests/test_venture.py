import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.core.config import settings
from app.models.venture_run import VentureRun
from app.services import venture_service as service
from app.services.llm_provider import llm_provider

BRIEF = "Criar um produto de agendamento para pequenos salões, sem orçamento para nuvem."


async def create(env, headers=None):
    headers = headers or env.a
    project = (await env.client.post("/projects", json={"name": "Meu produto"}, headers=headers)).json()
    response = await env.client.post(f"/venture/projects/{project['id']}/runs", json={"brief": BRIEF}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def read(env, run_id):
    return (await env.client.get(f"/venture/runs/{run_id}", headers=env.a)).json()


def events(response):
    assert response.status_code == 200, response.text
    return [(block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:])) for block in response.text.strip().split("\n\n")]


async def claim(env, run_id, user_id=None):
    async with env.factory() as db:
        return await service.claim_run(db, user_id or env.aid, uuid.UUID(run_id))


async def test_four_stages_save_export_and_review(env):
    run = await create(env)
    path = f"/venture/runs/{run['id']}"
    assert (await env.client.post(path + "/review", headers=env.a)).status_code == 409
    result = events(await env.client.post(path + "/stream", headers=env.a))
    assert result[-1] == ("done", {"status": "awaiting_review"})
    assert [data["key"] for event, data in result if event == "artifact"] == [step.key for step in service.STEPS]
    saved = await read(env, run["id"])
    assert saved["next_step"] == 4 and len(saved["artifacts"]) == 4
    assert saved["lease_expires_at"] is None
    assert len(env.prompts) == 4
    for index, prompt in enumerate(env.prompts):
        assert BRIEF in prompt[1]["content"]
        assert service.STEPS[index].instruction in prompt[0]["content"]
        for step in service.STEPS[:index]:
            assert step.title in prompt[1]["content"]
        assert "Não possui terminal" in prompt[0]["content"]
    export = await env.client.get(path + "/export", headers=env.a)
    assert "Nenhum código, teste ou deploy foi executado" in export.text
    assert BRIEF in export.text and "attachment" in export.headers["content-disposition"]
    assert export.text.count("Olá, resposta de teste.") == 4
    assert (await env.client.post(path + "/stream", headers=env.a)).status_code == 409
    reviewed = (await env.client.post(path + "/review", headers=env.a)).json()
    assert reviewed["status"] == "reviewed" and reviewed["reviewed_at"]
    repeated = (await env.client.post(path + "/review", headers=env.a)).json()["reviewed_at"]
    # SQLite drops timezone metadata; both stored instants must still be identical.
    assert datetime.fromisoformat(repeated).replace(tzinfo=timezone.utc) == datetime.fromisoformat(reviewed["reviewed_at"]).replace(tzinfo=timezone.utc)


async def test_owner_controls_every_workflow_route(env):
    run = await create(env)
    prefix = f"/venture/projects/{run['project_id']}/runs"
    for method, path, payload in [
        ("GET", prefix, None), ("POST", prefix, {"brief": BRIEF}),
        ("GET", f"/venture/runs/{run['id']}", None),
        ("GET", f"/venture/runs/{run['id']}/export", None),
        *[("POST", f"/venture/runs/{run['id']}/{action}", None) for action in ["stream", "pause", "review"]],
    ]:
        response = await env.client.request(method, path, headers=env.b, **({"json": payload} if payload else {}))
        assert response.status_code == 404, (method, path, response.text)
    assert (await env.client.get(prefix)).status_code == 401
    listed = (await env.client.get(prefix, headers=env.a)).json()
    assert len(listed) == 1 and listed[0]["id"] == run["id"]
    assert "artifacts" not in listed[0] and "brief" not in listed[0]


async def test_brief_validation(env):
    run = await create(env)
    for brief in ["curto", " " * 20, "a" * 6001]:
        result = await env.client.post(f"/venture/projects/{run['project_id']}/runs", json={"brief": brief}, headers=env.a)
        assert result.status_code == 422


async def test_failure_resumes_only_unfinished_stages(env, monkeypatch):
    run = await create(env)
    calls = 0
    async def fail_second(messages):
        nonlocal calls
        calls += 1
        yield "Documento completo" if calls == 1 else "Rascunho incompleto"
        if calls == 2:
            raise RuntimeError("private-provider-secret")
    monkeypatch.setattr(llm_provider, "stream_chat", fail_second)
    response = await env.client.post(f"/venture/runs/{run['id']}/stream", headers=env.a)
    assert events(response)[-1] == ("done", {"status": "failed"})
    assert "private-provider-secret" not in response.text
    failed = await read(env, run["id"])
    assert failed["next_step"] == 1 and len(failed["artifacts"]) == 1
    checkpoint = failed["artifacts"][0]
    assert failed["status"] == "failed"
    assert "Rascunho incompleto" not in json.dumps(failed["artifacts"])
    assert events(await env.client.post(f"/venture/runs/{run['id']}/stream", headers=env.a))[-1][1]["status"] == "awaiting_review"
    resumed = await read(env, run["id"])
    assert calls == 5 and resumed["artifacts"][0] == checkpoint
    assert len(resumed["artifacts"]) == 4 and resumed["error_message"] is None


@pytest.mark.parametrize("mode", ["empty", "oversized", "timeout"])
async def test_incomplete_output_never_becomes_a_checkpoint(env, monkeypatch, mode):
    run = await create(env)
    monkeypatch.setattr(settings, "VENTURE_STEP_TIMEOUT_SECONDS", .03)
    async def output(messages):
        if mode == "timeout":
            await asyncio.sleep(1)
        yield " " if mode == "empty" else "a" * (settings.VENTURE_MAX_OUTPUT_CHARS + 1)
    monkeypatch.setattr(llm_provider, "stream_chat", output)
    result = events(await env.client.post(f"/venture/runs/{run['id']}/stream", headers=env.a))
    assert result[-1] == ("done", {"status": "failed"})
    saved = await read(env, run["id"])
    assert saved["next_step"] == 0 and saved["artifacts"] == [] and saved["status"] == "failed"


async def test_only_one_active_workflow_per_user(env):
    first, second, other = await create(env), await create(env), await create(env, env.b)
    await claim(env, first["id"])
    for run_id in [first["id"], second["id"]]:
        with pytest.raises(HTTPException) as error:
            await claim(env, run_id)
        assert error.value.status_code == 409
    row, _ = await claim(env, other["id"], env.bid)
    assert row.status == "running"


async def test_pause_and_restart_fence_old_results(env):
    run = await create(env)
    row, token = await claim(env, run["id"])
    saved = (await env.client.post(f"/venture/runs/{run['id']}/pause", headers=env.a)).json()
    assert saved["status"] == "paused" and saved["lease_expires_at"] is None
    _, new_token = await claim(env, run["id"])
    assert not await service.save_artifact(row.id, token, 0, [{"content": "old"}])
    await service.finish(row.id, token, "failed", "old error")
    assert await service.active(row.id, new_token)
    assert (await read(env, run["id"]))["error_message"] is None


async def test_stale_work_is_recoverable(env):
    first, second = await create(env), await create(env)
    row, token = await claim(env, first["id"])
    async with env.factory() as db:
        await db.execute(update(VentureRun).where(VentureRun.id == row.id).values(lease_expires_at=service.utcnow() - timedelta(seconds=1)))
        await db.commit()
    await claim(env, second["id"])
    assert (await read(env, first["id"]))["status"] == "paused"
    assert not await service.active(row.id, token)


@pytest.mark.parametrize("during_output", [False, True])
async def test_disconnect_pauses_and_closes_provider(env, monkeypatch, during_output):
    run = await create(env)
    row, token = await claim(env, run["id"])
    closed = []
    async def source(messages):
        try:
            yield "incompleto"
            await asyncio.sleep(1)
        finally:
            closed.append(True)
    monkeypatch.setattr(llm_provider, "stream_chat", source)
    stream = service.run_stream(row, token)
    assert (await anext(stream)).startswith("event: start")
    if during_output:
        assert (await anext(stream)).startswith("event: stage")
        assert (await anext(stream)).startswith("event: chunk")
    await stream.aclose()
    saved = await read(env, run["id"])
    assert saved["status"] == "paused" and saved["artifacts"] == []
    assert closed == ([True] if during_output else [])


async def test_database_write_failure_is_not_success(env, monkeypatch):
    run = await create(env)
    async def broken(*args):
        raise RuntimeError("private-database-secret")
    monkeypatch.setattr(service, "save_artifact", broken)
    response = await env.client.post(f"/venture/runs/{run['id']}/stream", headers=env.a)
    assert events(response)[-1] == ("done", {"status": "failed"})
    assert "private-database-secret" not in response.text
    assert (await read(env, run["id"]))["artifacts"] == []


async def test_cancelling_while_waiting_for_model_pauses_run(env, monkeypatch):
    run = await create(env)
    row, token = await claim(env, run["id"])
    started, closed = asyncio.Event(), asyncio.Event()
    async def blocked(messages):
        started.set()
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()
    monkeypatch.setattr(llm_provider, "stream_chat", blocked)
    async def consume():
        async for _ in service.run_stream(row, token):
            pass
    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    saved = await read(env, run["id"])
    assert saved["status"] == "paused" and saved["next_step"] == 0


async def test_project_deletion_removes_workflows(env):
    run = await create(env)
    assert (await env.client.delete(f"/projects/{run['project_id']}", headers=env.a)).status_code == 204
    assert (await env.client.get(f"/venture/runs/{run['id']}", headers=env.a)).status_code == 404


def test_context_bound_keeps_brief_and_represents_every_prior_stage():
    brief = "Requisito do fundador. " * 260
    artifacts = [{"title": step.title, "content": "a" * 12000} for step in service.STEPS[:3]]
    prompt = service.build_step_prompt(service.STEPS[3], brief, artifacts)
    assert sum(len(item["content"]) for item in prompt) <= settings.PROVIDER_CONTEXT_TOKEN_BUDGET * 4
    assert brief in prompt[1]["content"] and brief not in prompt[0]["content"]
    for artifact in artifacts:
        assert artifact["title"] in prompt[1]["content"]
    assert "Trecho limitado" in prompt[1]["content"]
