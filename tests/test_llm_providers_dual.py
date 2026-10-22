import httpx
import pytest

from app.core.config import get_settings
from app.services.llm_provider import (
    FallbackLLMProvider,
    GeminiProvider,
    GroqProvider,
    LLMAuthenticationError,
    LLMProvider,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMResponse,
    OllamaProvider,
    create_provider_by_name,
    get_llm_provider,
)


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


ORIG_ASYNC_CLIENT = httpx.AsyncClient


def make_mock_client_factory(handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = MockTransport(handler)
        return ORIG_ASYNC_CLIENT(*args, **kwargs)
    return factory


# --- GeminiProvider Tests ---

@pytest.mark.anyio
async def test_gemini_provider_missing_api_key():
    provider = GeminiProvider(api_key=None)
    with pytest.raises(LLMAuthenticationError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert "Gemini API key is not configured" in str(exc_info.value)


@pytest.mark.anyio
async def test_gemini_provider_successful_response(monkeypatch):
    async def mock_handler(request: httpx.Request):
        assert "x-goog-api-key" in request.headers
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello! I can help you with ultrasonic nozzles."}
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, json=data)

    provider = GeminiProvider(api_key="test-gemini-key")
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    response = await provider.generate_chat_response(
        messages=[{"role": "user", "content": "Hi"}],
        system_prompt="You are a sales rep.",
    )
    assert response.content == "Hello! I can help you with ultrasonic nozzles."
    assert response.model == "gemini-3.8-flash"


@pytest.mark.anyio
async def test_gemini_provider_auth_error(monkeypatch):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(400, json={"error": {"message": "API_KEY_INVALID"}})

    provider = GeminiProvider(api_key="bad-key", max_retries=0)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    with pytest.raises(LLMAuthenticationError):
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])


@pytest.mark.anyio
async def test_gemini_provider_rate_limit(monkeypatch):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})

    provider = GeminiProvider(api_key="test-key", max_retries=0)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    with pytest.raises(LLMRateLimitError):
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])


@pytest.mark.anyio
async def test_gemini_provider_timeout(monkeypatch):
    async def mock_handler(request: httpx.Request):
        raise httpx.TimeoutException("Timed out")

    provider = GeminiProvider(api_key="test-key", timeout_seconds=1.0, max_retries=0)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    with pytest.raises(LLMProviderUnavailableError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])
    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_gemini_provider_503_unavailable_and_retries(monkeypatch):
    call_count = 0

    async def mock_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            503,
            json={"error": {"code": 503, "message": "High demand. Please try again later.", "status": "UNAVAILABLE"}},
        )

    provider = GeminiProvider(api_key="test-key", max_retries=1)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    with pytest.raises(LLMProviderUnavailableError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])
    assert "503" in str(exc_info.value)
    assert call_count == 2  # 1 initial + 1 retry


@pytest.mark.anyio
async def test_gemini_provider_404_not_found(monkeypatch):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(404, json={"error": {"message": "models/bad-model is not found"}})

    provider = GeminiProvider(api_key="test-key", model="bad-model", max_retries=1)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    with pytest.raises(LLMProviderUnavailableError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])
    assert "404" in str(exc_info.value)
    assert "bad-model" in str(exc_info.value)


# --- GroqProvider Tests ---

@pytest.mark.anyio
async def test_groq_provider_missing_api_key():
    provider = GroqProvider(api_key=None)
    with pytest.raises(LLMAuthenticationError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert "Groq API key is not configured" in str(exc_info.value)


@pytest.mark.anyio
async def test_groq_provider_successful_response(monkeypatch):
    async def mock_handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer test-groq-key"
        data = {
            "model": "llama-3.3-70b-versatile",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Welcome to WaveNxD! How may I assist your spray application?",
                    }
                }
            ],
        }
        return httpx.Response(200, json=data)

    provider = GroqProvider(api_key="test-groq-key", model="llama-3.3-70b-versatile")
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    response = await provider.generate_chat_response(
        messages=[{"role": "user", "content": "Hi"}],
        system_prompt="Sales rep",
    )
    assert "Welcome to WaveNxD" in response.content
    assert response.model == "llama-3.3-70b-versatile"


@pytest.mark.anyio
async def test_groq_provider_rate_limit_and_auth_errors(monkeypatch):
    provider = GroqProvider(api_key="test-key")

    # 401 Auth error
    async def mock_auth_err(request: httpx.Request):
        return httpx.Response(401, json={"error": "Unauthorized"})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_auth_err))
    with pytest.raises(LLMAuthenticationError):
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])

    # 429 Rate limit error
    async def mock_rate_err(request: httpx.Request):
        return httpx.Response(429, json={"error": "Rate limit reached"})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_rate_err))
    with pytest.raises(LLMRateLimitError):
        await provider.generate_chat_response([{"role": "user", "content": "Hi"}])


# --- FallbackLLMProvider Tests ---

class MockSuccessLLM(LLMProvider):
    def __init__(self, name: str):
        self.name = name

    async def generate_chat_response(self, messages, system_prompt=None):
        return LLMResponse(content=f"Response from {self.name}", model=self.name)


class MockFailingLLM(LLMProvider):
    def __init__(self, exc: Exception):
        self.exc = exc

    async def generate_chat_response(self, messages, system_prompt=None):
        raise self.exc


@pytest.mark.anyio
async def test_fallback_provider_primary_success():
    primary = MockSuccessLLM("primary")
    fallback = MockSuccessLLM("fallback")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    resp = await provider.generate_chat_response([{"role": "user", "content": "hi"}])
    assert resp.content == "Response from primary"


@pytest.mark.anyio
async def test_fallback_provider_switches_on_unavailable_and_rate_limit():
    # Test fallback on 503 unavailable
    failing_primary = MockFailingLLM(LLMProviderUnavailableError("Connection dropped"))
    fallback = MockSuccessLLM("groq-fallback")
    provider = FallbackLLMProvider(primary=failing_primary, fallback=fallback)

    resp = await provider.generate_chat_response([{"role": "user", "content": "hi"}])
    assert resp.content == "Response from groq-fallback"

    # Test fallback on 429 rate limit
    rate_limited_primary = MockFailingLLM(LLMRateLimitError("Quota exceeded"))
    provider2 = FallbackLLMProvider(primary=rate_limited_primary, fallback=fallback)
    resp2 = await provider2.generate_chat_response([{"role": "user", "content": "hi"}])
    assert resp2.content == "Response from groq-fallback"


@pytest.mark.anyio
async def test_fallback_provider_raises_when_fallback_also_fails():
    primary = MockFailingLLM(LLMProviderUnavailableError("Primary failed"))
    fallback = MockFailingLLM(LLMProviderUnavailableError("Fallback also failed"))
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    with pytest.raises(LLMProviderUnavailableError) as exc_info:
        await provider.generate_chat_response([{"role": "user", "content": "hi"}])
    assert "Fallback also failed" in str(exc_info.value)


# --- Factory get_llm_provider Tests ---

def test_create_provider_by_name():
    assert isinstance(create_provider_by_name("gemini"), GeminiProvider)
    assert isinstance(create_provider_by_name("groq"), GroqProvider)
    assert isinstance(create_provider_by_name("ollama"), OllamaProvider)
    assert isinstance(create_provider_by_name("unknown"), OllamaProvider)


def test_get_llm_provider_with_fallback_configuration(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_fallback_enabled", True)
    monkeypatch.setattr(settings, "llm_fallback_provider", "groq")

    provider = get_llm_provider()
    assert isinstance(provider, FallbackLLMProvider)
    assert isinstance(provider.primary, GeminiProvider)
    assert isinstance(provider.fallback, GroqProvider)


def test_get_llm_provider_fallback_disabled_by_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "llm_fallback_enabled", False)

    provider = get_llm_provider()
    assert isinstance(provider, GroqProvider)
