import re

import httpx

from app.core.config import settings

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchError(Exception):
    """Erro ao consultar o Tavily — sempre tratado como best-effort no chat.py."""


# Heurística leve pra decidir se a pergunta precisa de dado atual/recente.
# Mesmo espírito da detecção de "pedido de código": não precisa ser perfeita,
# só evitar buscar à toa em perguntas atemporais.
_FRESHNESS_KEYWORDS = re.compile(
    r"\b("
    r"hoje|agora|atual|atualmente|recente|últim[oa]s?|essa semana|esse mês|"
    r"notícias?|cota[cç][aã]o|pre[cç]o (de|do|da)|clima|tempo em|"
    r"quem [ée] o atual|quando (foi|ser[aá])|ontem|20[2-9]\d"
    r")\b",
    re.IGNORECASE,
)


def needs_web_search(message: str) -> bool:
    return bool(_FRESHNESS_KEYWORDS.search(message))


async def search_web(query: str) -> list[dict]:
    """
    Busca no Tavily e devolve uma lista de {title, url, content} resumidos.
    Levanta WebSearchError em qualquer falha — quem chama decide o que fazer
    (no nosso caso, seguir sem contexto web em vez de derrubar a conversa).
    """
    if not settings.TAVILY_API_KEY:
        raise WebSearchError("TAVILY_API_KEY não configurada")

    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": settings.WEB_SEARCH_MAX_RESULTS,
        "include_answer": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.WEB_SEARCH_TIMEOUT) as client:
            response = await client.post(TAVILY_URL, json=payload)
    except httpx.HTTPError as exc:
        raise WebSearchError(f"Falha de conexão com o Tavily: {exc}") from exc

    if response.status_code != 200:
        raise WebSearchError(f"Tavily retornou erro {response.status_code}: {response.text}")

    data = response.json()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in data.get("results", [])
    ]


def format_web_context(results: list[dict]) -> str:
    """Formata os resultados de busca como um bloco de contexto pro system prompt."""
    if not results:
        return ""

    lines = ["Resultados de busca na web (use para responder com informação atualizada):"]
    for i, r in enumerate(results, start=1):
        lines.append(f"{i}. {r['title']} — {r['url']}\n   {r['content']}")
    lines.append(
        "Cite a fonte (nome/URL) quando usar essas informações na resposta. "
        "Se os resultados não forem suficientes pra responder com confiança, diga isso."
    )
    return "\n".join(lines)
