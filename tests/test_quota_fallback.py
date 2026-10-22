import io
from unittest.mock import AsyncMock, patch
from bson import ObjectId
import httpx
import pytest
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.models.conversation import Conversation
from app.models.recommendation import CustomerRequirements
from app.services.llm_provider import (
    FallbackLLMProvider,
    GeminiProvider,
    GroqProvider,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMResponse,
    LLMServiceOverloadError,
    LLMTransientRateLimitError,
    get_llm_provider,
    parse_rate_limit_details,
    provider_circuit_breaker,
    sleep_with_backoff,
)
from app.services.voice_service import (
    GeminiTTSProvider,
    GroqWhisperSTTProvider,
    get_stt_provider,
    get_tts_provider,
)
from tests.test_conversations import conversation_context, login_user


class MockSimpleLLM(LLMProvider):
    def __init__(self, name: str, response_content: str | None = None, raise_exc: Exception | None = None):
        self._name = name
        self.response_content = response_content
        self.raise_exc = raise_exc
        self.call_count = 0

    @property
    def provider_id(self) -> str:
        return self._name

    async def generate_chat_response(self, messages, system_prompt=None, correlation_id=None):
        self.call_count += 1
        if self.raise_exc:
            raise self.raise_exc
        return LLMResponse(
            content=self.response_content or f"Response from {self._name}",
            model=self._name,
        )


# --- 1. Primary Success ---

@pytest.mark.anyio
async def test_quota_fallback_primary_success():
    primary = MockSimpleLLM("primary-groq", response_content="Primary success")
    secondary = MockSimpleLLM("secondary-gemini", response_content="Secondary not used")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    resp = await fallback_provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert resp.content == "Primary success"
    assert primary.call_count == 1
    assert secondary.call_count == 0


# --- 2. Fallback on Transient 503 Overload ---

@pytest.mark.anyio
async def test_quota_fallback_on_primary_service_overload():
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMServiceOverloadError("Groq 503 overload"))
    secondary = MockSimpleLLM("secondary-gemini", response_content="Secondary response on 503")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    resp = await fallback_provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert resp.content == "Secondary response on 503"
    assert primary.call_count == 1
    assert secondary.call_count == 1


# --- 3. Fallback on Transient 429 Rate Limit ---

@pytest.mark.anyio
async def test_quota_fallback_on_primary_transient_rate_limit():
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMTransientRateLimitError("Groq RPM exceeded", retry_after=2.0))
    secondary = MockSimpleLLM("secondary-gemini", response_content="Secondary response on 429")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    resp = await fallback_provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert resp.content == "Secondary response on 429"
    assert primary.call_count == 1
    assert secondary.call_count == 1


# --- 4. Fallback on Daily Quota Exhausted & Circuit Breaker Cooldown ---

@pytest.mark.anyio
async def test_quota_fallback_on_exhausted_daily_quota_and_circuit_breaker():
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMQuotaExhaustedError("Groq daily token limit reached"))
    secondary = MockSimpleLLM("secondary-gemini", response_content="Secondary gemini response")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    # First call: primary fails with QuotaExhausted, trips breaker, secondary succeeds
    resp1 = await fallback_provider.generate_chat_response([{"role": "user", "content": "First req"}])
    assert resp1.content == "Secondary gemini response"
    assert primary.call_count == 1
    assert secondary.call_count == 1

    # Record quota exhaustion in circuit breaker
    await provider_circuit_breaker.record_failure("primary-groq", is_quota_exhaustion=True, cooldown_seconds=600.0)
    assert not await provider_circuit_breaker.is_available("primary-groq")

    # Second call: primary is in cooldown, bypassed immediately, secondary invoked directly
    resp2 = await fallback_provider.generate_chat_response([{"role": "user", "content": "Second req"}])
    assert resp2.content == "Secondary gemini response"
    assert primary.call_count == 1  # Primary call count did NOT increase
    assert secondary.call_count == 2


# --- 5. Non-Retryable: Invalid Credentials (No Fallback) ---

@pytest.mark.anyio
async def test_no_fallback_on_invalid_credentials():
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMAuthenticationError("Invalid Groq API key"))
    secondary = MockSimpleLLM("secondary-gemini", response_content="Should not be called")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    with pytest.raises(LLMAuthenticationError) as exc_info:
        await fallback_provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert "Invalid Groq API key" in str(exc_info.value)
    assert primary.call_count == 1
    assert secondary.call_count == 0


# --- 6. Non-Retryable: Invalid Model Configuration (No Fallback) ---

@pytest.mark.anyio
async def test_no_fallback_on_invalid_model_config():
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMConfigurationError("Model not found (HTTP 404)"))
    secondary = MockSimpleLLM("secondary-gemini", response_content="Should not be called")
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)

    with pytest.raises(LLMConfigurationError) as exc_info:
        await fallback_provider.generate_chat_response([{"role": "user", "content": "Hello"}])
    assert "Model not found" in str(exc_info.value)
    assert primary.call_count == 1
    assert secondary.call_count == 0


# --- 7. Both Providers Fail: HTTP 503 & Preserved Conversation History ---

def test_both_providers_fail_returns_safe_503_and_preserves_history(conversation_context):
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMProviderUnavailableError("Groq down"))
    secondary = MockSimpleLLM("secondary-gemini", raise_exc=LLMProviderUnavailableError("Gemini down"))
    both_failing = FallbackLLMProvider(primary=primary, fallback=secondary)

    app.dependency_overrides[get_llm_provider] = lambda: both_failing

    try:
        with TestClient(app) as client:
            auth = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Please suggest a nozzle for 5 ml/min flow."},
                headers=headers,
            )
            assert resp.status_code == 503
            detail = resp.json()["detail"]
            assert "temporarily unavailable" in detail.lower()
            # Must NOT expose raw provider stack trace or internal exception names
            assert "traceback" not in detail.lower()
            assert "primary-groq" not in detail

            # Conversation in MongoDB still exists with only the initial greeting and NO fabricated assistant messages
            db = conversation_context["db"]
            conv_doc = db.conversations_data[ObjectId(conv_id)]
            assert len(conv_doc["messages"]) == 1
            assert conv_doc["messages"][0]["role"] == "assistant"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


# --- 8. Rate Limit Details Parsing & Bounded Backoff Utilities ---

@pytest.mark.anyio
async def test_rate_limit_details_parser():
    # Daily quota signals
    gemini_daily_json = '{"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota). GenerateRequestsPerDay limit: 20 exceeded."}}'
    is_daily, retry_after, reason = parse_rate_limit_details(429, gemini_daily_json)
    assert is_daily is True
    assert "Daily quota exhausted" in reason

    # Transient burst with Retry-After header
    transient_json = '{"error": {"message": "Rate limit reached. Please try again in 2.5s"}}'
    headers = {"Retry-After": "2"}
    is_daily_2, retry_after_2, reason_2 = parse_rate_limit_details(429, transient_json, headers)
    assert is_daily_2 is False
    assert retry_after_2 == 2.0
    assert "Rate limit threshold reached" in reason_2

    # Bounded backoff
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await sleep_with_backoff(attempt=1, base_seconds=0.5, max_seconds=3.0, retry_after=10.0)
        # Sleep duration should be capped at max_seconds=3.0
        mock_sleep.assert_called_once()
        actual_slept = mock_sleep.call_args[0][0]
        assert actual_slept <= 3.0


# --- 9. Gemini TTS Quota Exhaustion: Text-Only Mode Offered ---

def test_gemini_tts_quota_exhaustion_offers_text_only(conversation_context):
    class MockQuotaExhaustedTTS:
        @property
        def supported_languages(self):
            return ["en"]

        async def synthesize_speech(self, text, language="en"):
            raise LLMQuotaExhaustedError("Gemini TTS daily limit reached")

    app.dependency_overrides[get_tts_provider] = lambda: MockQuotaExhaustedTTS()

    try:
        with TestClient(app) as client:
            auth = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            db = conversation_context["db"]
            oid = ObjectId(conv_id)
            db.conversations_data[oid]["messages"] = [
                {"id": "msg-u-1", "role": "user", "content": "Hi", "created_at": "2026-10-21T00:00:00Z"},
                {"id": "msg-a-1", "role": "assistant", "content": "Standard 60 kHz nozzle recommended.", "created_at": "2026-10-21T00:00:01Z"},
            ]

            speak_resp = client.post(
                f"/customer/conversations/{conv_id}/messages/msg-a-1/speak",
                headers=headers,
            )
            assert speak_resp.status_code == 503
            detail = speak_resp.json()["detail"]
            assert "daily quota reached" in detail.lower()
            assert "text-only mode" in detail.lower()

            # Assistant text response in conversation is completely preserved
            assert db.conversations_data[oid]["messages"][1]["content"] == "Standard 60 kHz nozzle recommended."
    finally:
        app.dependency_overrides.pop(get_tts_provider, None)


# --- 10. Groq Whisper STT Failure: Text Input Mode Offered ---

def test_groq_whisper_stt_failure_offers_text_input(conversation_context):
    class MockFailingSTT:
        async def transcribe_audio(self, audio_bytes, filename, content_type, language=None):
            raise LLMQuotaExhaustedError("Groq Whisper rate limit exceeded")

    app.dependency_overrides[get_stt_provider] = lambda: MockFailingSTT()

    try:
        with TestClient(app) as client:
            auth = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            fake_wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

            voice_resp = client.post(
                f"/customer/conversations/{conv_id}/voice-messages",
                files={"file": ("sample.wav", io.BytesIO(fake_wav), "audio/wav")},
                headers=headers,
            )
            assert voice_resp.status_code == 503
            detail = voice_resp.json()["detail"]
            assert "temporarily unavailable" in detail.lower()
            assert "text input" in detail.lower()
    finally:
        app.dependency_overrides.pop(get_stt_provider, None)


# --- 11. Preservation of Deterministic Recommendation & Company Authorization ---

def test_fallback_preserves_deterministic_recommendation_and_isolation(conversation_context):
    """
    Verifies Requirement 9: Provider fallback must not bypass product authorization,
    change catalog eligibility, invent product specifications, or mark an unverified product as a match.
    """
    # Primary fails with 503, secondary succeeds and extracts requirement updates
    primary = MockSimpleLLM("primary-groq", raise_exc=LLMServiceOverloadError("Groq overloaded"))
    secondary = MockSimpleLLM(
        "secondary-gemini",
        response_content="We recommend the WaveNxD 60 kHz nozzle. ```json\n{\"requirements_update\": {\"application\": \"spray drying\", \"flow_rate_ml_min\": 2.5, \"viscosity_cp\": 15.0}}\n```",
    )
    fallback_provider = FallbackLLMProvider(primary=primary, fallback=secondary)
    app.dependency_overrides[get_llm_provider] = lambda: fallback_provider

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers_a)
            conv_id = conv_resp.json()["id"]

            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "We need a spray drying nozzle with 2.5 ml/min flow rate and 15 cP viscosity."},
                headers=headers_a,
            )
            assert msg_resp.status_code == 200
            data = msg_resp.json()
            rec = data["recommendation_result"]

            # Company A has standard-nozzle-60khz assigned (max 50 ml/min, max 50 cP) -> MATCH
            assert rec["overall_outcome"] == ProductMatchStatus.MATCH
            evals = rec["candidate_evaluations"]
            keys = [e["catalog_key"] for e in evals]
            assert "standard-nozzle-60khz" in keys
            # Company B product high-flow-conical-60khz MUST NOT appear
            assert "high-flow-conical-60khz" not in keys
            # Verify primary was attempted and secondary was called
            assert primary.call_count == 1
            assert secondary.call_count == 1
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
