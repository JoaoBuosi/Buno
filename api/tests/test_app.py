import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
import uuid
import pytest
from PIL import Image
from sqlalchemy import select
from app.api.v1.endpoints import chat
from app.core.config import settings
from app.core.security import create_access_token
from app.models.document import Document
from app.models.memory import Memory
from app.services.llm_provider import llm_provider, LLMProviderResponseError
from tests.conftest import PASSWORD


def events(response):
    assert response.status_code == 200, response.text
    result = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result

async def conversation(env, headers=None, **payload):
    response = await env.client.post("/conversations", json=payload, headers=headers or env.a)
    assert response.status_code == 201, response.text
    return response.json()["id"]

async def test_register_login_and_profile(env):
    result = await env.client.post("/auth/register", json={"email": "joao@example.com", "name": "João", "password": PASSWORD})
    assert result.status_code == 201
    auth = {"Authorization": f"Bearer {result.json()['access_token']}"}
    profile = (await env.client.get("/auth/me", headers=auth)).json()
    assert profile["name"] == "João" and profile["memory_enabled"] is False
    result = await env.client.post("/auth/login", data={"username": "joao@example.com", "password": PASSWORD})
    assert result.status_code == 200
    assert (await env.client.post("/auth/login", data={"username": "joao@example.com", "password": "errada"})).status_code == 401
    assert (await env.client.post("/auth/register", json={"email": "joao@example.com", "password": PASSWORD})).status_code == 400

async def test_auth_validation_and_deleted_user_token(env):
    for password in ["curta", "á" * 40]:
        assert (await env.client.post("/auth/register", json={"email": "invalid@example.com", "password": password})).status_code == 422
    assert (await env.client.get("/conversations")).status_code == 401
    ghost = {"Authorization": f"Bearer {create_access_token(uuid.uuid4())}"}
    assert (await env.client.get("/conversations", headers=ghost)).status_code == 401

async def test_project_ownership_and_nonblank_name(env):
    assert (await env.client.post("/projects", json={"name": "   "}, headers=env.a)).status_code == 422
    pid = (await env.client.post("/projects", json={"name": "Buno"}, headers=env.a)).json()["id"]
    cid = await conversation(env, project_id=pid)
    assert (await env.client.get(f"/conversations?project_id={pid}", headers=env.a)).json()[0]["id"] == cid
    assert (await env.client.get(f"/projects/{pid}", headers=env.b)).status_code == 404
    assert (await env.client.post("/conversations", json={"project_id": pid}, headers=env.b)).status_code == 404
    assert (await env.client.post("/chat/stream", json={"message": "Olá", "project_id": pid}, headers=env.b)).status_code == 404
    other = await conversation(env, env.b)
    assert (await env.client.patch(f"/conversations/{other}/project", json={"project_id": pid}, headers=env.b)).status_code == 404

async def test_chat_persists_order_title_and_context(env):
    cid = await conversation(env)
    result = events(await env.client.post("/chat/stream", json={"message": "Minha primeira pergunta", "conversation_id": cid}, headers=env.a))
    assert result[0] == ("start", {"conversation_id": cid})
    assert result[-1] == ("done", {})
    saved = (await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).json()
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[-1]["content"] == "Olá, resposta de teste."
    events(await env.client.post("/chat/stream", json={"message": "E agora?", "conversation_id": cid}, headers=env.a))
    assert [m["role"] for m in env.prompts[-1]] == ["system", "user", "assistant", "user"]
    assert env.prompts[-1][-1]["content"] == "E agora?"
    listing = (await env.client.get("/conversations", headers=env.a)).json()
    assert listing[0]["title"] == "Minha primeira pergunta"
    assert (await env.client.patch(f"/conversations/{cid}", json={"title": "Planejamento"}, headers=env.a)).json()["title"] == "Planejamento"
    assert (await env.client.patch(f"/conversations/{cid}", json={"title": "  "}, headers=env.a)).status_code == 422

async def test_edit_user_message_truncates_followups_and_regenerates(env):
    cid = await conversation(env)
    events(await env.client.post("/chat/stream", json={"message": "Primeira versão", "conversation_id": cid}, headers=env.a))
    first = (await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).json()[0]
    events(await env.client.post("/chat/stream", json={"message": "Pergunta seguinte", "conversation_id": cid}, headers=env.a))
    response = await env.client.post("/chat/stream", json={"message": "Versão corrigida", "conversation_id": cid, "edit_message_id": first["id"]}, headers=env.a)
    assert events(response)[-1] == ("done", {})
    saved = (await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).json()
    assert [item["role"] for item in saved] == ["user", "assistant"]
    assert saved[0]["content"] == "Versão corrigida"
    assert all("Pergunta seguinte" not in item["content"] for item in saved)
    assert env.prompts[-1][-1]["content"] == "Versão corrigida"

async def test_only_owned_user_messages_can_be_edited(env):
    cid = await conversation(env)
    events(await env.client.post("/chat/stream", json={"message": "Pergunta", "conversation_id": cid}, headers=env.a))
    messages = (await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).json()
    assistant_id = messages[-1]["id"]
    assert (await env.client.post("/chat/stream", json={"message": "Novo", "conversation_id": cid, "edit_message_id": assistant_id}, headers=env.a)).status_code == 422
    assert (await env.client.post("/chat/stream", json={"message": "Invasão", "conversation_id": cid, "edit_message_id": messages[0]["id"]}, headers=env.b)).status_code == 404

async def test_conversation_isolation_and_deletion(env):
    cid = await conversation(env)
    for method, path, payload in [("get", f"/conversations/{cid}/messages", None), ("delete", f"/conversations/{cid}", None), ("patch", f"/conversations/{cid}", {"title": "invadida"}), ("post", "/chat/stream", {"message": "oi", "conversation_id": cid})]:
        response = await env.client.request(method, path, headers=env.b, **({"json": payload} if payload else {}))
        assert response.status_code == 404
    assert (await env.client.get("/conversations", headers=env.b)).json() == []
    assert (await env.client.delete(f"/conversations/{cid}", headers=env.a)).status_code == 204
    assert (await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).status_code == 404

async def test_document_available_on_first_message_without_embeddings(env):
    cid = await conversation(env)
    result = await env.client.post("/documents", data={"conversation_id": cid}, files={"file": ("../plano.txt", "O projeto Buno deve começar pelo cadastro.", "text/plain")}, headers=env.a)
    assert result.status_code == 201, result.text
    doc = result.json()
    assert doc["filename"] == "plano.txt" and doc["text_extracted"] is True
    response = await env.client.post("/chat/stream", json={"message": "Como começar o projeto?", "conversation_id": cid}, headers=env.a)
    assert events(response)[-1] == ("done", {})
    assert "deve começar pelo cadastro" in env.prompts[-1][-1]["content"]
    assert "deve começar pelo cadastro" not in env.prompts[-1][0]["content"]
    async with env.factory() as db:
        stored = await db.get(Document, uuid.UUID(doc["id"]))
        raw = Path(stored.storage_path)
    assert raw.exists() and raw.with_suffix(".txt").exists()
    assert (await env.client.delete(f"/documents/{doc['id']}", headers=env.a)).status_code == 204
    assert not raw.exists() and not raw.with_suffix(".txt").exists()

async def test_document_ownership_and_invalid_uploads(env):
    cid = await conversation(env)
    alien = await conversation(env, env.b)
    upload = {"file": ("a.txt", b"conteudo", "text/plain")}
    assert (await env.client.post("/documents", data={"conversation_id": cid}, files=upload, headers=env.b)).status_code == 404
    doc = (await env.client.post("/documents", data={"conversation_id": cid}, files=upload, headers=env.a)).json()
    assert (await env.client.patch(f"/documents/{doc['id']}/attach", json={"conversation_id": alien}, headers=env.a)).status_code == 404
    assert (await env.client.delete(f"/documents/{doc['id']}", headers=env.b)).status_code == 404
    for filename, data, mime, status in [("a.txt", b"", "text/plain", 422), ("a.exe", b"binary", "application/octet-stream", 415), ("bad.png", b"broken", "image/png", 422), ("bad.pdf", b"broken", "application/pdf", 422)]:
        assert (await env.client.post("/documents", data={"conversation_id": cid}, files={"file": (filename, data, mime)}, headers=env.a)).status_code == status

async def test_image_forwarded_to_model(env):
    cid = await conversation(env)
    image = BytesIO(); Image.new("RGB", (8, 8), "blue").save(image, format="PNG"); data = image.getvalue()
    result = await env.client.post("/documents", data={"conversation_id": cid}, files={"file": ("foto.png", data, "image/png")}, headers=env.a)
    assert result.status_code == 201
    assert result.json()["text_extracted"] is False
    events(await env.client.post("/chat/stream", json={"message": "O que aparece?", "conversation_id": cid}, headers=env.a))
    assert env.prompts[-1][-1]["images"] == [base64.b64encode(data).decode()]

async def test_optional_context_timeout_does_not_block_chat(env, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(1)
        return ["não deveria chegar"]
    monkeypatch.setattr(chat, "retrieve_relevant_memories", slow)
    assert events(await env.client.post("/chat/stream", json={"message": "Olá"}, headers=env.a))[-1] == ("done", {})

async def test_provider_error_is_safe_and_partial_answer_not_persisted(env, monkeypatch):
    async def broken(messages):
        yield "Trecho parcial"
        raise LLMProviderResponseError(500, "private-provider-trace-secret")
    monkeypatch.setattr(llm_provider, "stream_chat", broken)
    cid = await conversation(env)
    response = await env.client.post("/chat/stream", json={"message": "Olá", "conversation_id": cid}, headers=env.a)
    result = events(response)
    assert "private-provider" not in response.text
    assert result[-2][0] == "error" and result[-1] == ("done", {"status": "error"})
    assert len((await env.client.get(f"/conversations/{cid}/messages", headers=env.a)).json()) == 1

async def test_save_failure_does_not_report_success(env, monkeypatch):
    async def missing(*args):
        raise RuntimeError("private database failure")
    monkeypatch.setattr(chat, "owned_conversation", missing)
    response = await env.client.post("/chat/stream", json={"message": "Olá"}, headers=env.a)
    result = events(response)
    assert result[-2][0] == "error" and result[-1][1] == {"status": "error"}
    assert "private database failure" not in response.text

async def test_memory_consent_and_owner_controls(env):
    assert (await env.client.get("/auth/me", headers=env.a)).json()["memory_enabled"] is False
    assert (await env.client.patch("/auth/me", json={"memory_enabled": True}, headers=env.a)).json()["memory_enabled"] is True
    async with env.factory() as db:
        memory = Memory(user_id=env.aid, content="Prefere português", embedding=[.1] * settings.EMBEDDING_DIMENSIONS)
        db.add(memory); await db.commit(); mid = memory.id
    assert len((await env.client.get("/memories", headers=env.a)).json()) == 1
    assert (await env.client.get("/memories", headers=env.b)).json() == []
    assert (await env.client.delete(f"/memories/{mid}", headers=env.b)).status_code == 404
    assert (await env.client.patch("/auth/me", json={"memory_enabled": False}, headers=env.a)).json()["memory_enabled"] is False
    assert (await env.client.delete(f"/memories/{mid}", headers=env.a)).status_code == 204

async def test_message_limits_and_rate_limit(env, monkeypatch):
    for text in ["  ", "a" * 8001]:
        assert (await env.client.post("/chat/stream", json={"message": text}, headers=env.a)).status_code == 422
    monkeypatch.setattr(settings, "CHAT_REQUESTS_PER_MINUTE", 1)
    assert (await env.client.post("/chat/stream", json={"message": "Primeira"}, headers=env.a)).status_code == 200
    denied = await env.client.post("/chat/stream", json={"message": "Segunda"}, headers=env.a)
    assert denied.status_code == 429 and denied.headers["retry-after"] == "60"
    assert (await env.client.post("/chat/stream", json={"message": "Outro usuário"}, headers=env.b)).status_code == 200
