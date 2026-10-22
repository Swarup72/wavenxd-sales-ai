from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.llm_provider import (
    LLMProviderUnavailableError,
    OllamaProvider,
)


@pytest.mark.anyio
async def test_ollama_provider_success():
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")

    mock_response = httpx.Response(
        status_code=200,
        json={
            "model": "llama3",
            "message": {
                "role": "assistant",
                "content": "Hello! I can help you select an ultrasonic nozzle for your spray drying application.",
            },
            "done": True,
        },
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        res = await provider.generate_chat_response(
            messages=[{"role": "user", "content": "Hi"}],
            system_prompt="You are WaveNxD sales assistant.",
        )
        assert res.model == "llama3"
        assert "ultrasonic nozzle" in res.content


@pytest.mark.anyio
async def test_ollama_provider_timeout_raises_unavailable():
    provider = OllamaProvider(base_url="http://localhost:11434", timeout_seconds=1.0)

    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Timed out")):
        with pytest.raises(LLMProviderUnavailableError) as exc_info:
            await provider.generate_chat_response(messages=[{"role": "user", "content": "Hi"}])
        assert "timed out" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_ollama_provider_connection_error_raises_unavailable():
    provider = OllamaProvider(base_url="http://localhost:11434")

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(LLMProviderUnavailableError) as exc_info:
            await provider.generate_chat_response(messages=[{"role": "user", "content": "Hi"}])
        assert "could not connect" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_ollama_provider_empty_response_raises_unavailable():
    provider = OllamaProvider(base_url="http://localhost:11434")

    mock_response = httpx.Response(
        status_code=200,
        json={"model": "llama3", "message": {"role": "assistant", "content": ""}},
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(LLMProviderUnavailableError) as exc_info:
            await provider.generate_chat_response(messages=[{"role": "user", "content": "Hi"}])
        assert "empty response" in str(exc_info.value).lower()
