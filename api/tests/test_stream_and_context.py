import json
import httpx
import pytest
from app.services.document_extraction import chunk_text
from app.services.memory_service import trim_history_to_token_budget
from app.services.llm_provider import LLMProvider, LLMProviderError


def test_trim_keeps_latest_and_images_within_budget():
    messages = [{"role": "system", "content": "Regras"}, {"role": "user", "content": "a" * 50}, {"role": "assistant", "content": "b" * 50}, {"role": "user", "content": "Atual", "images": ["data"]}]
    result = trim_history_to_token_budget(messages, max_tokens=20)
    assert result[-1] == messages[-1]
    assert result[0] == messages[0]
    assert sum(len(m["content"]) for m in result) <= 80
    assert result[1]["role"] == "user"
    with pytest.raises(ValueError):
        trim_history_to_token_budget([{"role": "user", "content": "x" * 100}], max_tokens=1)

@pytest.mark.parametrize("size,overlap", [(0, 0), (10, 10), (10, 11), (10, -1)])
def test_chunk_invalid_limits_fail_instead_of_looping(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("Documento", size, overlap)

@pytest.mark.parametrize("finished", [False, True])
async def test_ollama_stream_requires_terminal_event(monkeypatch, finished):
    lines = [{"message": {"content": "Olá "}, "done": False}, {"message": {"content": "Buno"}, "done": finished}]
    def handler(request):
        payload = json.loads(request.content)
        assert payload["messages"][-1]["images"] == ["img-base64"]
        return httpx.Response(200, text="\n".join(json.dumps(line) for line in lines))
    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    async def collect():
        return "".join([part async for part in LLMProvider().stream_chat([{"role": "user", "content": "Oi", "images": ["img-base64"]}])])
    if finished:
        assert await collect() == "Olá Buno"
    else:
        with pytest.raises(LLMProviderError) as error:
            await collect()
            assert error.value.code == "llm_interrupted"


async def test_ollama_output_token_limit_is_not_a_completed_answer(monkeypatch):
    def handler(request):
        return httpx.Response(200, text=json.dumps({"message": {"content": "Resposta cortada"}, "done": True, "done_reason": "length"}))
    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(LLMProviderError) as error:
        _ = [part async for part in LLMProvider().stream_chat([{"role": "user", "content": "Oi"}])]
    assert error.value.code == "llm_output_limit"
