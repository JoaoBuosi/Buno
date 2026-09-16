"""Integração mínima, real e opcional com o Microsoft Foundry.

O cliente é importado somente quando o recurso é usado. Assim, a instalação
local com Ollama continua funcionando sem Azure configurado. A chamada do SDK
é síncrona, por isso fica em uma thread quando chamada pelo FastAPI/CLI.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("buno.foundry")


class FoundryConfigurationError(RuntimeError):
    """Configuração ausente ou incompleta para o projeto Foundry."""


class FoundryProviderError(RuntimeError):
    """Falha segura ao criar ou executar um agente no Foundry."""


@dataclass(frozen=True)
class FoundryRunResult:
    agent_id: str
    agent_name: str
    agent_version: str
    conversation_id: str
    output_text: str


@dataclass(frozen=True)
class FoundryProvisionResult:
    agent_id: str
    agent_name: str
    agent_version: str


def foundry_configured() -> bool:
    return bool(
        settings.FOUNDRY_ENABLED
        and settings.FOUNDRY_PROJECT_ENDPOINT.strip()
        and settings.FOUNDRY_MODEL.strip()
        and settings.FOUNDRY_AGENT_NAME.strip()
    )


def foundry_status() -> dict[str, object]:
    """Retorna apenas estado/configuração não sensível para o dashboard."""
    endpoint = settings.FOUNDRY_PROJECT_ENDPOINT.strip()
    return {
        "enabled": settings.FOUNDRY_ENABLED,
        "configured": foundry_configured(),
        "project_endpoint_set": bool(endpoint),
        "model_set": bool(settings.FOUNDRY_MODEL.strip()),
        "agent_name": settings.FOUNDRY_AGENT_NAME.strip() or None,
    }


def _configuration_error() -> FoundryConfigurationError:
    return FoundryConfigurationError(
        "Foundry não está configurado. Preencha FOUNDRY_PROJECT_ENDPOINT, "
        "FOUNDRY_MODEL e FOUNDRY_AGENT_NAME em api/.env, defina FOUNDRY_ENABLED=true "
        "e autentique com az login."
    )


def _run_sync(prompt: str) -> FoundryRunResult:
    if not foundry_configured():
        raise _configuration_error()

    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import PromptAgentDefinition
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise FoundryProviderError(
            "Dependências do Foundry ausentes. Execute `pip install -r requirements.txt` na pasta api."
        ) from exc

    credential = None
    project = None
    try:
        credential = DefaultAzureCredential()
        project = AIProjectClient(
            endpoint=settings.FOUNDRY_PROJECT_ENDPOINT.strip(),
            credential=credential,
        )
        # Uma versão nova torna o teste repetível e deixa o agente visível no
        # projeto para inspeção no portal. Não são criadas ferramentas externas.
        agent = project.agents.create_version(
            agent_name=settings.FOUNDRY_AGENT_NAME.strip(),
            definition=PromptAgentDefinition(
                model=settings.FOUNDRY_MODEL.strip(),
                instructions=settings.FOUNDRY_AGENT_INSTRUCTIONS,
            ),
        )
        agent_name = str(getattr(agent, "name", settings.FOUNDRY_AGENT_NAME.strip()))
        openai = project.get_openai_client(agent_name=agent_name)
        conversation = openai.conversations.create()
        response = openai.responses.create(
            conversation=conversation.id,
            input=prompt,
        )
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise FoundryProviderError("O agente Foundry retornou uma resposta vazia.")
        return FoundryRunResult(
            agent_id=str(getattr(agent, "id", "")),
            agent_name=agent_name,
            agent_version=str(getattr(agent, "version", "")),
            conversation_id=str(conversation.id),
            output_text=output_text,
        )
    except FoundryProviderError:
        raise
    except Exception as exc:  # SDK errors can contain URLs/headers; do not echo them.
        logger.warning("Falha no Foundry (%s)", type(exc).__name__)
        raise FoundryProviderError(
            "Não foi possível criar ou executar o agente Foundry. Confira endpoint, "
            "modelo implantado, permissões Foundry User e `az login`."
        ) from exc
    finally:
        for client in (project, credential):
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # limpeza best-effort; não esconde o resultado
                    logger.debug("Falha ao fechar cliente Foundry", exc_info=True)


async def run_agent_task(prompt: str) -> FoundryRunResult:
    """Cria uma versão de agente e executa uma tarefa real com timeout."""
    if not prompt.strip():
        raise ValueError("A tarefa do Foundry não pode estar vazia.")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_sync, prompt.strip()),
            timeout=settings.FOUNDRY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise FoundryProviderError(
            "O agente Foundry excedeu o tempo limite configurado."
        ) from exc


def _provision_sync(agent_name: str, model: str, instructions: str) -> FoundryProvisionResult:
    if not foundry_configured():
        raise _configuration_error()
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import PromptAgentDefinition
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise FoundryProviderError(
            "Dependências do Foundry ausentes. Execute `pip install -r requirements.txt` na pasta api."
        ) from exc

    credential = None
    project = None
    try:
        credential = DefaultAzureCredential()
        project = AIProjectClient(endpoint=settings.FOUNDRY_PROJECT_ENDPOINT.strip(), credential=credential)
        agent = project.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(model=model, instructions=instructions),
        )
        return FoundryProvisionResult(
            agent_id=str(getattr(agent, "id", "")),
            agent_name=str(getattr(agent, "name", agent_name)),
            agent_version=str(getattr(agent, "version", "")),
        )
    except FoundryProviderError:
        raise
    except Exception as exc:
        logger.warning("Falha ao provisionar agente Foundry (%s)", type(exc).__name__)
        raise FoundryProviderError(
            "Não foi possível provisionar o agente no Foundry. Confira endpoint, modelo, "
            "permissões Foundry User e `az login`."
        ) from exc
    finally:
        for client in (project, credential):
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("Falha ao fechar cliente Foundry", exc_info=True)


async def provision_agent(agent_name: str, model: str, instructions: str) -> FoundryProvisionResult:
    """Cria uma versão de agente no Foundry sem bloquear o event loop."""
    return await asyncio.wait_for(
        asyncio.to_thread(_provision_sync, agent_name.strip(), model.strip(), instructions),
        timeout=settings.FOUNDRY_TIMEOUT_SECONDS,
    )
