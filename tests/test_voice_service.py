import base64
import io
import httpx
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMProvider,
    LLMProviderUnavailableError,
    LLMResponse,
    get_llm_provider,
)
from app.services.voice_service import (
    AudioValidationError,
    GeminiTTSProvider,
    GroqTTSProvider,
    GroqWhisperSTTProvider,
    STTProvider,
    TTSProvider,
    TTSUnsupportedLanguageError,
    get_stt_provider,
    get_tts_provider,
    validate_audio_upload,
)
from tests.test_conversations import conversation_context, login_user

ORIG_ASYNC_CLIENT = httpx.AsyncClient


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


def make_mock_client_factory(handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = MockTransport(handler)
        return ORIG_ASYNC_CLIENT(*args, **kwargs)
    return factory


# --- Validation Tests ---

def test_validate_audio_upload_success():
    # Valid WAV
    validate_audio_upload("sample.wav", "audio/wav", 1024, max_size_bytes=5000)
    # Valid MP3
    validate_audio_upload("recording.mp3", "audio/mpeg", 2048, max_size_bytes=5000)
    # Valid M4A
    validate_audio_upload("note.m4a", "audio/m4a", 2048, max_size_bytes=5000)


def test_validate_audio_upload_failures():
    # Empty
    with pytest.raises(AudioValidationError) as exc:
        validate_audio_upload("test.wav", "audio/wav", 0)
    assert "empty" in str(exc.value).lower()

    # Oversized
    with pytest.raises(AudioValidationError) as exc:
        validate_audio_upload("large.wav", "audio/wav", 10000, max_size_bytes=5000)
    assert "exceeds maximum" in str(exc.value).lower()

    # Unsupported format
    with pytest.raises(AudioValidationError) as exc:
        validate_audio_upload("script.sh", "application/x-sh", 500)
    assert "unsupported audio format" in str(exc.value).lower()

    # Invalid MIME type
    with pytest.raises(AudioValidationError) as exc:
        validate_audio_upload("audio.wav", "text/plain", 500)
    assert "unsupported audio content type" in str(exc.value).lower()


# --- STT Provider Tests ---

@pytest.mark.anyio
async def test_groq_whisper_missing_api_key():
    stt = GroqWhisperSTTProvider(api_key=None)
    with pytest.raises(LLMAuthenticationError):
        await stt.transcribe_audio(b"dummy", "audio.wav", "audio/wav")


@pytest.mark.anyio
async def test_groq_whisper_successful_transcription(monkeypatch):
    async def mock_handler(request: httpx.Request):
        assert "Authorization" in request.headers
        assert "multipart/form-data" in request.headers.get("content-type", "")
        return httpx.Response(200, json={"text": "We need a spray nozzle for lab spray drying with 3 ml/min flow."})

    stt = GroqWhisperSTTProvider(api_key="test-groq-key")
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    text = await stt.transcribe_audio(b"audio_bytes", "audio.wav", "audio/wav", language="en")
    assert "lab spray drying" in text


# --- TTS Provider Tests ---

@pytest.mark.anyio
async def test_gemini_tts_provider_success(monkeypatch):
    mock_audio_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt MOCK_AUDIO_DATA"
    encoded_audio = base64.b64encode(mock_audio_bytes).decode("utf-8")

    async def mock_handler(request: httpx.Request):
        assert "x-goog-api-key" in request.headers
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        body = httpx.Request("POST", "http://test", json=request.read()).json() if hasattr(request, "json") else {}
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/wav",
                                        "data": encoded_audio,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    tts = GeminiTTSProvider(api_key="test-gemini-key", model="gemini-3.8-flash-lite-tts", max_retries=1)
    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_handler))

    # Test English
    audio_bytes, ct = await tts.synthesize_speech("Hello, this is WaveNxD.", language="en")
    assert ct == "audio/wav"
    assert audio_bytes == mock_audio_bytes

    # Test Hindi
    audio_bytes_hi, ct_hi = await tts.synthesize_speech("नमस्ते WaveNxD", language="hi")
    assert ct_hi == "audio/wav"
    assert audio_bytes_hi == mock_audio_bytes

    # Test Marathi
    audio_bytes_mr, ct_mr = await tts.synthesize_speech("नमस्कार WaveNxD", language="mr")
    assert ct_mr == "audio/wav"
    assert audio_bytes_mr == mock_audio_bytes


@pytest.mark.anyio
async def test_gemini_tts_provider_validations():
    tts = GeminiTTSProvider(api_key="test-gemini-key")

    # Empty text
    with pytest.raises(ValueError) as exc:
        await tts.synthesize_speech("   ")
    assert "empty text" in str(exc.value).lower()

    # Oversized text
    with pytest.raises(ValueError) as exc:
        await tts.synthesize_speech("x" * (tts.max_chars + 1))
    assert "exceeds max allowed" in str(exc.value).lower()

    # Unsupported language
    with pytest.raises(TTSUnsupportedLanguageError) as exc:
        await tts.synthesize_speech("Bonjour", language="fr")
    assert "supports: en, hi, mr, hinglish" in str(exc.value)

    # Missing API key
    tts_no_key = GeminiTTSProvider(api_key=None)
    with pytest.raises(LLMAuthenticationError) as exc:
        await tts_no_key.synthesize_speech("Hello")
    assert "api key is not configured" in str(exc.value).lower()


@pytest.mark.anyio
async def test_gemini_tts_provider_api_errors(monkeypatch):
    tts = GeminiTTSProvider(api_key="test-key", max_retries=0)

    # 401 Auth error
    async def mock_auth_err(request: httpx.Request):
        return httpx.Response(401, json={"error": {"message": "API_KEY_INVALID"}})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_auth_err))
    with pytest.raises(LLMAuthenticationError):
        await tts.synthesize_speech("Hello")

    # 404 Model not found
    async def mock_not_found(request: httpx.Request):
        return httpx.Response(404, json={"error": {"message": "models/bad-tts not found"}})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_not_found))
    with pytest.raises(LLMProviderUnavailableError) as exc:
        await tts.synthesize_speech("Hello")
    assert "not found" in str(exc.value).lower()

    # Empty candidates
    async def mock_empty_candidates(request: httpx.Request):
        return httpx.Response(200, json={"candidates": []})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_empty_candidates))
    with pytest.raises(LLMProviderUnavailableError) as exc:
        await tts.synthesize_speech("Hello")
    assert "empty candidate list" in str(exc.value).lower()

    # Missing inlineData
    async def mock_no_audio(request: httpx.Request):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "no audio"}]}}]})

    monkeypatch.setattr(httpx, "AsyncClient", make_mock_client_factory(mock_no_audio))
    with pytest.raises(LLMProviderUnavailableError) as exc:
        await tts.synthesize_speech("Hello")
    assert "without audio data" in str(exc.value).lower()


@pytest.mark.anyio
async def test_groq_tts_provider():
    tts = GroqTTSProvider(api_key="test-groq-key")
    # English supported
    audio_bytes, ct = await tts.synthesize_speech("Standard nozzle is recommended.", language="en")
    assert ct == "audio/wav"

    # Marathi unsupported
    with pytest.raises(TTSUnsupportedLanguageError) as exc:
        await tts.synthesize_speech("नमस्कार", language="mr")
    assert "does not support language 'mr'" in str(exc.value)


# --- Customer API Voice Endpoints Tests ---

class MockVoiceLLM(LLMProvider):
    async def generate_chat_response(self, messages, system_prompt=None):
        return LLMResponse(
            content="""I recommend our Standard 60 kHz Ultrasonic Nozzle for your lab spray drying application.
```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "flow_rate_ml_min": 3.0,
    "viscosity_cp": 20.0
  },
  "unresolved_questions": []
}
```""",
            model="mock-voice-llm",
        )


class MockSTT(STTProvider):
    async def transcribe_audio(self, audio_bytes, filename, content_type, language=None):
        return "We need an ultrasonic nozzle for lab spray drying with 3.0 ml/min flow and 20 cP viscosity."


class MockTTS(TTSProvider):
    @property
    def supported_languages(self):
        return ["en"]

    async def synthesize_speech(self, text: str, language: str = "en"):
        if language != "en":
            raise TTSUnsupportedLanguageError(f"Language '{language}' is not supported")
        return b"RIFFMOCKWAVEAUDIO", "audio/wav"


def test_customer_voice_message_upload_and_pipeline(conversation_context):
    app.dependency_overrides[get_llm_provider] = lambda: MockVoiceLLM()
    app.dependency_overrides[get_stt_provider] = lambda: MockSTT()

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # Submit valid audio file
            audio_file = io.BytesIO(b"RIFFdummydataforwavfile")
            resp = client.post(
                f"/customer/conversations/{conv_id}/voice-messages",
                files={"file": ("speech.wav", audio_file, "audio/wav")},
                data={"language": "en"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()

            # Transcript became user message with modality 'voice'
            user_msg = data["user_message"]
            assert user_msg["input_modality"] == "voice"
            assert "lab spray drying" in user_msg["content"]

            # Requirements extracted from voice message
            reqs = data["updated_requirements"]
            assert reqs["application"] == "Lab spray drying"
            assert reqs["flow_rate_ml_min"] == 3.0
            assert reqs["viscosity_cp"] == 20.0

            # Recommendation evaluated
            assert data["recommendation_result"]["overall_outcome"] == ProductMatchStatus.MATCH
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
        app.dependency_overrides.pop(get_stt_provider, None)


def test_customer_voice_message_invalid_file(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        # Empty audio
        resp_empty = client.post(
            f"/customer/conversations/{conv_id}/voice-messages",
            files={"file": ("empty.wav", io.BytesIO(b""), "audio/wav")},
            headers=headers,
        )
        assert resp_empty.status_code == 400
        assert "empty" in resp_empty.json()["detail"].lower()

        # Invalid file extension
        resp_bad_ext = client.post(
            f"/customer/conversations/{conv_id}/voice-messages",
            files={"file": ("malicious.exe", io.BytesIO(b"data"), "application/octet-stream")},
            headers=headers,
        )
        assert resp_bad_ext.status_code == 400
        assert "unsupported audio format" in resp_bad_ext.json()["detail"].lower()


def test_customer_speak_assistant_message_and_isolation(conversation_context):
    app.dependency_overrides[get_tts_provider] = lambda: MockTTS()

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # Directly inject an assistant message and a user message in DB
            db = conversation_context["db"]
            oid = ObjectId(conv_id)
            db.conversations_data[oid]["messages"] = [
                {"id": "msg-user-1", "role": "user", "content": "Hello", "created_at": "2026-10-21T00:00:00Z"},
                {"id": "msg-asst-1", "role": "assistant", "content": "We recommend the 60 kHz nozzle.", "created_at": "2026-10-21T00:00:01Z"},
            ]

            # 1. Successful speak of assistant message (English)
            speak_resp = client.post(
                f"/customer/conversations/{conv_id}/messages/msg-asst-1/speak",
                headers=headers,
            )
            assert speak_resp.status_code == 200
            assert speak_resp.headers["content-type"] == "audio/wav"
            assert speak_resp.content == b"RIFFMOCKWAVEAUDIO"

            # 2. Reject speaking user message
            user_speak_resp = client.post(
                f"/customer/conversations/{conv_id}/messages/msg-user-1/speak",
                headers=headers,
            )
            assert user_speak_resp.status_code == 400
            assert "only permitted for assistant responses" in user_speak_resp.json()["detail"]

            # 3. Unsupported language returns 422
            unsupported_resp = client.post(
                f"/customer/conversations/{conv_id}/messages/msg-asst-1/speak?language=mr",
                headers=headers,
            )
            assert unsupported_resp.status_code == 422
            assert "not supported" in unsupported_resp.json()["detail"]

        # 4. Cross-customer isolation on speak endpoint using separate client
        with TestClient(app) as client_b:
            auth_b = login_user(client_b, "bob@betacoatings.com")
            b_headers = {"X-CSRF-Token": auth_b["csrf_token"]}
            cross_resp = client_b.post(
                f"/customer/conversations/{conv_id}/messages/msg-asst-1/speak",
                headers=b_headers,
            )
            assert cross_resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_tts_provider, None)
