"""Local browser verification only. Never use this simulated model in production.
Run from api/: python -m tests.preview_server
Creates an isolated database in a temporary directory and binds to loopback.
"""
import asyncio
import os
import tempfile
from pathlib import Path

preview_dir = Path(tempfile.mkdtemp(prefix="buno-preview-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{preview_dir / 'preview.db'}"
os.environ["JWT_SECRET"] = "local-preview-test-only-key"
os.environ["UPLOAD_DIR"] = str(preview_dir / "uploads")
os.environ["TAVILY_API_KEY"] = ""

from app.main import app
from app.db.base import Base
from app.db.session import engine
from app.services.llm_provider import llm_provider, LLMProviderUnavailableError

async def simulated_stream(messages):
    text = messages[-1]["content"]
    if "falha de teste" in text.lower():
        raise LLMProviderUnavailableError("Falha simulada para testar a interface.")
    if "Documentos da conversa" in text:
        answer = "Li o documento anexado. O primeiro passo é organizar o cadastro e o fluxo de conversas.\n\nEsta é uma resposta simulada para verificar os anexos."
    else:
        answer = "Vamos organizar sua ideia em três etapas:\n\n1. Definir o objetivo e quem vai usar.\n2. Construir o fluxo principal de conversa.\n3. Testar com exemplos reais.\n\nEsta é uma resposta simulada para verificar a interface."
    delay = .25 if "lenta" in text.lower() else .03
    for start in range(0, len(answer), 8):
        await asyncio.sleep(delay)
        yield answer[start:start + 8]

async def no_memory(messages):
    return "NADA"
async def no_embedding(text):
    raise LLMProviderUnavailableError()

llm_provider.stream_chat = simulated_stream
llm_provider.complete_chat = no_memory
llm_provider.embed = no_embedding

async def prepare():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

if __name__ == "__main__":
    import uvicorn
    asyncio.run(prepare())
    print("Buno: preview LOCAL com modelo SIMULADO. Nenhuma inferência real.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
