"""Agent registry, lifecycle actions, logs and user isolation."""

from __future__ import annotations


AGENT = {
    "name": "Agente Dev",
    "description": "Implementa e revisa código com segurança.",
    "instructions": "Você é um engenheiro de software cuidadoso e objetivo.",
    "profile": "developer",
    "model": "qwen3.5:9b",
    "provider": "ollama",
}


async def test_agent_lifecycle_logs_and_user_isolation(env):
    invalid = await env.client.post("/agents", json={**AGENT, "name": "  "}, headers=env.a)
    assert invalid.status_code == 422

    created = await env.client.post("/agents", json=AGENT, headers=env.a)
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["status"] == "active"
    assert agent["provider"] == "ollama"

    assert (await env.client.get("/agents", headers=env.b)).json() == []
    assert (await env.client.get(f"/agents/{agent['id']}", headers=env.b)).status_code == 404

    updated = await env.client.patch(
        f"/agents/{agent['id']}",
        json={"instructions": "Você é um engenheiro que também escreve testes."},
        headers=env.a,
    )
    assert updated.status_code == 200
    assert "também escreve testes" in updated.json()["instructions"]

    paused = await env.client.post(f"/agents/{agent['id']}/pause", headers=env.a)
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    resumed = await env.client.post(f"/agents/{agent['id']}/resume", headers=env.a)
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"

    logs = await env.client.get(f"/agents/{agent['id']}/logs?limit=20", headers=env.a)
    assert logs.status_code == 200
    assert {item["kind"] for item in logs.json()} >= {"created", "updated", "paused", "resumed"}
    assert (await env.client.get(f"/agents/{agent['id']}/logs", headers=env.b)).status_code == 404

    assert (await env.client.delete(f"/agents/{agent['id']}", headers=env.b)).status_code == 404
    assert (await env.client.delete(f"/agents/{agent['id']}", headers=env.a)).status_code == 204
    assert (await env.client.get("/agents", headers=env.a)).json() == []


async def test_foundry_agent_reports_safe_configuration_error(env):
    created = await env.client.post(
        "/agents",
        json={**AGENT, "name": "Agente Azure", "provider": "foundry", "model": "gpt-4o"},
        headers=env.a,
    )
    assert created.status_code == 201, created.text
    # ASGITransport waits for FastAPI background tasks, so an unconfigured local
    # environment finishes in error; a real Azure setup may finish as active.
    result = created.json()
    assert result["status"] in {"provisioning", "active", "error"}
    if result["status"] == "error":
        assert "credential" not in (result["last_error"] or "").lower()
