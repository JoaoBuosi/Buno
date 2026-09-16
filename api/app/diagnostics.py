"""Local diagnostics. No credentials are printed and no database rows are changed."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

import httpx
from sqlalchemy import select, text


@dataclass(frozen=True)
class Check:
    item: str
    status: str
    detalhe: str
    acao: str = ""


def report(checks: list[Check]) -> dict:
    return {"pronto": not any(c.status == "erro" for c in checks), "verificacoes": [asdict(c) for c in checks]}


def normalized_model(name: str) -> str:
    # A port in a registry hostname is not a model tag.
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


async def database_checks(factory, expected_heads: set[str], timeout: float = 5) -> list[Check]:
    from app.db.base import Base
    checks = []
    try:
        async with asyncio.timeout(timeout):
            async with factory() as db:
                await db.execute(text("SELECT 1"))
                checks.append(Check("banco", "ok", "Conexão com o banco estabelecida."))
                if db.get_bind().dialect.name != "postgresql":
                    checks.append(Check("pgvector", "erro", "Esta configuração não usa PostgreSQL.", "Use PostgreSQL com pgvector para rodar a Buno; SQLite é usado somente nos testes."))
                else:
                    installed = (await db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))).scalar_one_or_none()
                    checks.append(Check("pgvector", "ok" if installed else "erro", "Extensão vetorial encontrada." if installed else "A extensão pgvector ainda não está instalada.", "" if installed else "Confira o banco e execute python buno.py migrar."))
                try:
                    actual = set((await db.execute(text("SELECT version_num FROM alembic_version"))).scalars().all())
                    if actual != expected_heads:
                        checks.append(Check("migracoes", "erro", "A versão do banco difere da versão esperada por este código.", "Confira se está usando o banco correto e aplique as migrações correspondentes com python buno.py migrar."))
                    else:
                        for table in Base.metadata.sorted_tables:
                            await db.execute(select(table).limit(0))
                        checks.append(Check("migracoes", "ok", "Versão, tabelas e colunas esperadas foram encontradas."))
                except Exception:
                    checks.append(Check("migracoes", "erro", "As tabelas esperadas não estão disponíveis ou faltam permissões de leitura.", "Confira DATABASE_URL e execute python buno.py migrar no banco escolhido."))
    except Exception:
        return [Check("banco", "erro", "Não foi possível concluir a conexão ao banco dentro do prazo.", "Confira se o banco está ligado e se DATABASE_URL, rede, credenciais e SSL estão corretos.")]
    return checks


async def _probe_chat(client, config) -> Check:
    try:
        async with asyncio.timeout(120):
            response = await client.post(config.PROVIDER_BASE_URL.rstrip("/") + "/api/chat", json={
                "model": config.PROVIDER_CHAT_MODEL,
                "messages": [{"role": "user", "content": "Responda apenas: Buno pronta."}],
                "stream": False, "think": False, "options": {"num_predict": 24},
            }, timeout=120)
            response.raise_for_status()
            result = response.json()
            answer = result.get("message", {}).get("content")
            if result.get("done") is not True or not isinstance(answer, str) or not answer.strip():
                raise ValueError("Incomplete model response")
        return Check("geracao_real", "ok", "O modelo gerou uma resposta curta e concluiu a geração.")
    except Exception:
        return Check("geracao_real", "erro", "O modelo não concluiu o teste de resposta em até 120 segundos.", "Confira o modelo de chat e os recursos disponíveis no Ollama. Nenhuma mensagem foi salva no banco.")


async def _probe_embedding(client, config) -> Check:
    try:
        async with asyncio.timeout(120):
            response = await client.post(config.PROVIDER_BASE_URL.rstrip("/") + "/api/embed", json={
                "model": config.PROVIDER_EMBEDDING_MODEL, "input": "Buno: teste local de conexão."
            }, timeout=120)
            response.raise_for_status()
            embedding = response.json()["embeddings"][0]
            if not isinstance(embedding, list) or len(embedding) != config.EMBEDDING_DIMENSIONS:
                return Check("embedding_real", "erro", "O tamanho do vetor retornado não corresponde à configuração.", "Confira PROVIDER_EMBEDDING_MODEL e EMBEDDING_DIMENSIONS. As migrações atuais usam 768 dimensões.")
        return Check("embedding_real", "ok", "O modelo de embeddings respondeu com a dimensão configurada.")
    except Exception:
        return Check("embedding_real", "erro", "O modelo de embeddings não concluiu o teste em até 120 segundos.", "Confira o modelo de embeddings no Ollama.")


async def ollama_checks(client, config, *, generate: bool = False, timeout: float = 5) -> list[Check]:
    try:
        async with asyncio.timeout(timeout):
            response = await client.get(config.PROVIDER_BASE_URL.rstrip("/") + "/api/tags", timeout=timeout)
            response.raise_for_status()
            models = response.json()["models"]
            if not isinstance(models, list):
                raise ValueError("Invalid model list")
            available = {normalized_model(name) for entry in models if isinstance(entry, dict)
                         for name in [entry.get("name") or entry.get("model")] if isinstance(name, str)}
    except Exception:
        return [Check("ollama", "erro", "Não foi possível obter a lista de modelos do Ollama.", "Abra o Ollama e confira PROVIDER_BASE_URL em api/.env.")]
    chat = normalized_model(config.PROVIDER_CHAT_MODEL) in available
    embedding = normalized_model(config.PROVIDER_EMBEDDING_MODEL) in available
    checks = [
        Check("ollama", "ok", "Ollama respondeu à consulta de modelos."),
        Check("modelo_chat", "ok" if chat else "erro", "Modelo de chat encontrado." if chat else "O modelo de chat configurado não foi encontrado.", "" if chat else "Confira ollama list e PROVIDER_CHAT_MODEL; baixe o modelo escolhido com ollama pull."),
        Check("modelo_embedding", "ok" if embedding else "aviso", "Modelo de embeddings encontrado." if embedding else "O modelo de embeddings configurado não foi encontrado.", "" if embedding else "O chat simples pode funcionar; instale o modelo de embeddings para memórias e busca semântica."),
    ]
    if generate:
        # Sequential: avoid loading two large models concurrently on a local GPU.
        if chat:
            checks.append(await _probe_chat(client, config))
        if embedding:
            checks.append(await _probe_embedding(client, config))
    return checks


async def inspect(config, factory, expected_heads: set[str], *, generate: bool = False, client=None) -> dict:
    secret = config.JWT_SECRET
    configuration = Check("configuracao", "ok", "Configuração carregada; credenciais ocultas.")
    if secret == "substitua-por-um-segredo-aleatorio" or not secret:
        configuration = Check("configuracao", "erro", "JWT_SECRET ainda está com o valor do exemplo.", "Defina um segredo aleatório no arquivo api/.env. Não compartilhe esse valor.")
    if client is None:
        async with httpx.AsyncClient(timeout=5) as http:
            db, ollama = await asyncio.gather(database_checks(factory, expected_heads), ollama_checks(http, config, generate=generate))
    else:
        db, ollama = await asyncio.gather(database_checks(factory, expected_heads), ollama_checks(client, config, generate=generate))
    return report([configuration, *db, *ollama])


def print_report(result: dict, *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for check in result["verificacoes"]:
        print(f"[{check['status'].upper()}] {check['item']}: {check['detalhe']}")
        if check["acao"]:
            print(f"  Como resolver: {check['acao']}")
    print("\nConferência concluída. Pode iniciar a Buno." if result["pronto"] else "\nResolva os itens [ERRO] antes de iniciar.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico local da Buno, sem alterar seu banco.")
    parser.add_argument("--gerar", action="store_true", help="Também testa geração real e embeddings; pode levar até 4 minutos no total")
    parser.add_argument("--json", action="store_true", help="Saída estruturada sem credenciais")
    args = parser.parse_args(argv)
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from app.core.config import settings
        from app.db.session import AsyncSessionLocal, engine
        api_dir = Path(__file__).resolve().parents[1]
        heads = set(ScriptDirectory.from_config(Config(str(api_dir / "alembic.ini"))).get_heads())
        async def collect():
            try:
                return await inspect(settings, AsyncSessionLocal, heads, generate=args.gerar)
            finally:
                await engine.dispose()
        result = asyncio.run(collect())
    except KeyboardInterrupt:
        return 130
    except Exception:
        result = report([Check("configuracao", "erro", "Não foi possível carregar a configuração e as dependências da API.", "Execute python buno.py preparar e confira api/.env. Nenhuma credencial será exibida.")])
    print_report(result, json_output=args.json)
    if not args.gerar and not args.json:
        print("Este diagnóstico consultou conexão e modelos; use --gerar para testar uma resposta real.")
    return 0 if result["pronto"] else 1


if __name__ == "__main__":
    sys.exit(main())
