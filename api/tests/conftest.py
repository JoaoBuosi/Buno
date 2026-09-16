"""Isolated SQLite endpoint tests; vector search and model inference are simulated."""
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "buno-test-only-key-never-use-in-production"
os.environ["TAVILY_API_KEY"] = ""

from types import SimpleNamespace
from copy import deepcopy
import httpx
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models.user import User
from app.core.config import settings
from app.core.security import hash_password, create_access_token
from app.core.rate_limit import _windows
from app.services.llm_provider import llm_provider, LLMProviderUnavailableError
from app.api.v1.endpoints import chat
from app.api.v1.endpoints import agents
from app.services import venture_service
from app.services import governance_service

PASSWORD = "teste-Buno-2026"
PASSWORD_HASH = hash_password(PASSWORD)

@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(chat, "AsyncSessionLocal", factory)
    monkeypatch.setattr(agents, "AsyncSessionLocal", factory)
    monkeypatch.setattr(venture_service, "AsyncSessionLocal", factory)
    monkeypatch.setattr(governance_service, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "MEMORY_LOOKUP_TIMEOUT", .05)
    monkeypatch.setattr(settings, "DOCUMENT_PROCESS_TIMEOUT", .05)
    _windows.clear()
    prompts = []
    async def stream(messages):
        prompts.append(deepcopy(messages))
        yield "Olá, "
        yield "resposta de teste."
    async def no_memory(messages):
        return "NADA"
    async def embedding_unavailable(text):
        raise LLMProviderUnavailableError()
    monkeypatch.setattr(llm_provider, "stream_chat", stream)
    monkeypatch.setattr(llm_provider, "complete_chat", no_memory)
    monkeypatch.setattr(llm_provider, "embed", embedding_unavailable)
    async with factory() as db:
        alice = User(email="alice@example.com", name="Alice", hashed_password=PASSWORD_HASH)
        bob = User(email="bob@example.com", name="Bob", hashed_password=PASSWORD_HASH)
        db.add_all([alice, bob]); await db.commit()
        aid, bid = alice.id, bob.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1") as client:
        yield SimpleNamespace(client=client, factory=factory, prompts=prompts, tmp=tmp_path,
            a={"Authorization": f"Bearer {create_access_token(aid)}"},
            b={"Authorization": f"Bearer {create_access_token(bid)}"}, aid=aid, bid=bid)
    app.dependency_overrides.clear()
    await engine.dispose()
