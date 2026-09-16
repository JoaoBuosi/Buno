import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.diagnostics import database_checks, normalized_model, ollama_checks, report

CONFIG = SimpleNamespace(PROVIDER_BASE_URL="http://ollama.test", PROVIDER_CHAT_MODEL="qwen3.5:9b", PROVIDER_EMBEDDING_MODEL="nomic-embed-text", EMBEDDING_DIMENSIONS=768)


@pytest.mark.parametrize("name,expected", [("nomic-embed-text", "nomic-embed-text:latest"), ("qwen3.5:9b", "qwen3.5:9b"), ("registry:5000/model", "registry:5000/model:latest")])
def test_model_names_use_exact_tag(name, expected):
    assert normalized_model(name) == expected


async def test_ollama_alias_and_missing_optional_embedding():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]}))) as client:
        result = await ollama_checks(client, CONFIG)
    assert report(result)["pronto"] is True
    assert next(c for c in result if c.item == "modelo_embedding").status == "aviso"


async def test_different_chat_tag_does_not_count_as_installed():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "qwen3.5:27b"}]}))) as client:
        result = await ollama_checks(client, CONFIG)
    assert report(result)["pronto"] is False
    assert next(c for c in result if c.item == "modelo_chat").status == "erro"


@pytest.mark.parametrize("kind", ["unavailable", "malformed"])
async def test_ollama_error_never_exposes_provider_details(kind):
    def handler(request):
        if kind == "unavailable":
            raise httpx.ConnectError("private-token-and-network-address")
        return httpx.Response(200, json={"private-detail": "private-token-and-network-address"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ollama_checks(client, CONFIG)
    assert report(result)["pronto"] is False
    assert "private-token" not in str(report(result))


@pytest.mark.parametrize("done,dimensions,ready", [(True, 768, True), (False, 768, False), (True, 512, False)])
async def test_explicit_generation_checks_completion_and_vector_size(done, dimensions, ready):
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"done": done, "message": {"content": "Buno pronta."}})
        return httpx.Response(200, json={"embeddings": [[.1] * dimensions]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ollama_checks(client, CONFIG, generate=True)
    assert requests == ["/api/tags", "/api/chat", "/api/embed"]
    assert report(result)["pronto"] is ready


async def test_database_reports_pending_migration_then_valid_schema(env):
    checks = await database_checks(env.factory, {"0004"})
    assert next(c for c in checks if c.item == "migracoes").status == "erro"
    async with env.factory() as db:
        await db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await db.execute(text("INSERT INTO alembic_version VALUES ('0004')"))
        await db.commit()
    checks = await database_checks(env.factory, {"0004"})
    assert next(c for c in checks if c.item == "migracoes").status == "ok"
    # SQLite verifies tables in these tests; it is not accepted as the production DB.
    assert next(c for c in checks if c.item == "pgvector").status == "erro"


async def test_database_timeout_is_bounded_and_does_not_expose_credentials():
    @asynccontextmanager
    async def hanging():
        await asyncio.sleep(1)
        raise RuntimeError("postgresql://private:password@private-host/db")
        yield
    checks = await database_checks(hanging, {"0004"}, timeout=.01)
    assert report(checks)["pronto"] is False
    assert "password" not in str(report(checks))
