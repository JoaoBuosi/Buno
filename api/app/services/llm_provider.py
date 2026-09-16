import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.services.call_meter import current_meter

logger = logging.getLogger("buno.llm_provider")


class LLMProviderError(Exception):
    """
    Erro genérico ao falar com o provedor de IA. Sempre carrega um `code`
    estável — é isso que vira o JSON padronizado que o endpoint /chat/stream
    manda pro front no evento 'error', em vez de expor stacktrace/texto solto.
    """

    def __init__(self, message: str, code: str = "llm_provider_error"):
        self.code = code
        super().__init__(message)


class LLMProviderUnavailableError(LLMProviderError):
    """Ollama não respondeu depois de todas as tentativas (serviço fora do ar)."""

    def __init__(self, message: str = "Não foi possível conectar ao Ollama. Ele está rodando?"):
        super().__init__(message, code="llm_unavailable")


class LLMProviderTimeoutError(LLMProviderError):
    """A chamada ao Ollama passou do tempo limite configurado."""

    def __init__(self, message: str = "O modelo demorou demais para responder"):
        super().__init__(message, code="llm_timeout")


class LLMProviderResponseError(LLMProviderError):
    """Ollama respondeu, mas com erro HTTP (ex: modelo não encontrado/não baixado)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(
            f"Ollama retornou erro {status_code}: {detail}", code="llm_response_error"
        )


class LLMProvider:
    """
    Única parte do código que fala com o modelo de IA (hoje, Ollama local).
    Se um dia trocar de provedor, só essa classe muda.
    """

    def __init__(self) -> None:
        self._base_url = settings.PROVIDER_BASE_URL
        self._chat_model = settings.PROVIDER_CHAT_MODEL
        self._embedding_model = settings.PROVIDER_EMBEDDING_MODEL
        # Timeouts generosos: inferência local (principalmente com "cold start",
        # carregando o modelo na VRAM na primeira chamada) demora bem mais que
        # uma API na nuvem. connect curto (falha rápido se o Ollama nem estiver
        # de pé); read longo (a geração em si pode legitimamente demorar).
        self._timeout = httpx.Timeout(
            connect=settings.PROVIDER_CONNECT_TIMEOUT,
            read=settings.PROVIDER_READ_TIMEOUT,
            write=30.0,
            pool=10.0,
        )

    @staticmethod
    def _to_ollama_messages(messages: list[dict]) -> list[dict]:
        return [
            {"role": m["role"], "content": m["content"], **({"images": m["images"]} if m.get("images") else {})}
            for m in messages
        ]

    async def _open_stream_with_retry(
        self, stack: AsyncExitStack, client: httpx.AsyncClient, url: str, payload: dict
    ) -> httpx.Response:
        """
        Tenta abrir a conexão de streaming, com retry + backoff só na fase de
        CONEXÃO (antes do primeiro byte chegar). Depois que o streaming começa,
        não tentamos de novo — reenviar nesse ponto duplicaria texto que o
        usuário já viu na tela.
        """
        last_error: Exception | None = None

        for attempt in range(1, settings.PROVIDER_MAX_RETRIES + 1):
            try:
                return await stack.enter_async_context(
                    client.stream("POST", url, json=payload)
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_error = exc
                logger.warning(
                    "Falha ao conectar no Ollama (tentativa %s/%s): %s",
                    attempt,
                    settings.PROVIDER_MAX_RETRIES,
                    exc,
                )
                if attempt < settings.PROVIDER_MAX_RETRIES:
                    await asyncio.sleep(settings.PROVIDER_RETRY_BACKOFF_SECONDS * attempt)

        raise LLMProviderUnavailableError() from last_error

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """
        Manda a conversa pro Ollama e vai liberando pedaços (chunks) de texto
        conforme chegam — isso é o que alimenta o SSE do endpoint /chat/stream.
        100% assíncrono: não bloqueia o event loop do FastAPI enquanto espera
        o modelo gerar.
        """
        url = f"{self._base_url}/api/chat"
        meter = current_meter.get()
        payload = {
            "model": self._chat_model,
            "messages": self._to_ollama_messages(messages),
            "stream": True,
            # desliga o modo de "raciocínio" do Qwen3.5 — ele gasta muito tempo de
            # geração pensando antes de responder, mesmo quando não mostramos isso
            # na tela. Pra um chat rápido, vale mais a resposta direta.
            "think": False,
            "options": {"num_predict": meter.max_output_tokens if meter else settings.PROVIDER_MAX_TOKENS},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with AsyncExitStack() as stack:
                try:
                    response = await self._open_stream_with_retry(stack, client, url, payload)
                except httpx.ConnectError as exc:
                    raise LLMProviderUnavailableError() from exc

                if response.status_code != 200:
                    error_body = await response.aread()
                    raise LLMProviderResponseError(
                        response.status_code, error_body.decode(errors="replace")
                    )

                try:
                    finished = False
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise LLMProviderError("O modelo não conseguiu concluir a resposta", "llm_response_error")
                        text = chunk.get("message", {}).get("content")
                        if text:
                            yield text
                        if chunk.get("done"):
                            if meter:
                                for source, target in [("prompt_eval_count", "input_tokens"), ("eval_count", "output_tokens")]:
                                    count = chunk.get(source)
                                    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                                        setattr(meter, target, count)
                            if chunk.get("done_reason") == "length":
                                raise LLMProviderError("O modelo atingiu o limite antes de concluir a resposta", "llm_output_limit")
                            finished = True
                            break
                    if not finished:
                        raise LLMProviderError("A resposta foi interrompida. Tente novamente.", "llm_interrupted")
                except httpx.ReadTimeout as exc:
                    raise LLMProviderTimeoutError() from exc

    async def complete_chat(self, messages: list[dict]) -> str:
        """
        Versão não-streaming do chat — usada para tarefas internas (ex: o
        memory_service pedindo pro modelo resumir o que vale a pena lembrar),
        não para responder o usuário diretamente.
        """
        chunks = [chunk async for chunk in self.stream_chat(messages)]
        return "".join(chunks)

    async def embed(self, text: str) -> list[float]:
        """Gera o embedding de um texto para guardar/buscar na tabela `memories`."""
        url = f"{self._base_url}/api/embed"
        payload = {"model": self._embedding_model, "input": text}

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, settings.PROVIDER_MAX_RETRIES + 1):
                try:
                    response = await client.post(url, json=payload)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_error = exc
                    logger.warning(
                        "Falha ao conectar no Ollama pra embedding (tentativa %s/%s): %s",
                        attempt,
                        settings.PROVIDER_MAX_RETRIES,
                        exc,
                    )
                    if attempt < settings.PROVIDER_MAX_RETRIES:
                        await asyncio.sleep(settings.PROVIDER_RETRY_BACKOFF_SECONDS * attempt)
            else:
                raise LLMProviderUnavailableError() from last_error

        if response.status_code != 200:
            raise LLMProviderResponseError(response.status_code, response.text)

        return response.json()["embeddings"][0]


# instância única reutilizada pela aplicação inteira
llm_provider = LLMProvider()
