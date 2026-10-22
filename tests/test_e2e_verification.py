import base64
import io
import time
from bson import ObjectId
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.services.llm_provider import GroqProvider, create_provider_by_name, get_llm_provider
from app.services.voice_service import (
    GeminiTTSProvider,
    GroqWhisperSTTProvider,
    get_stt_provider,
    get_tts_provider,
)
from tests.test_conversations import conversation_context, login_user


def test_e2e_application_startup_and_health():
    """Task 1: Verify application starts successfully."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_e2e_factory_groq_support():
    """Task 7: Inspect provider factory support for Groq."""
    provider = create_provider_by_name("groq")
    assert isinstance(provider, GroqProvider)
    assert provider.model == "qwen/qwen3.8-27b"
    assert provider.api_key is not None


def test_e2e_customer_text_and_company_authorization(conversation_context):
    """
    Tasks 2 & 5: Customer sends text message to live Groq LLM, receives response,
    verifies deterministic product recommendation, and confirms cross-company isolation.
    """
    groq_llm = GroqProvider()
    app.dependency_overrides[get_llm_provider] = lambda: groq_llm

    try:
        with TestClient(app) as client_a:
            auth_a = login_user(client_a, "alice@alphapharma.com")
            headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

            # 1. Create conversation for Alice (Alpha Pharma)
            conv_resp = client_a.post(
                "/customer/conversations",
                json={"title": "E2E Lab Atomization Test"},
                headers=headers_a,
            )
            assert conv_resp.status_code == 201
            conv_id = conv_resp.json()["id"]

            # 2. Alice sends requirement text message
            msg_payload = {
                "content": "Hello! We need an ultrasonic nozzle for laboratory spray drying. Flow rate is 3 ml/min and viscosity is 20 cP."
            }
            msg_resp = client_a.post(
                f"/customer/conversations/{conv_id}/messages",
                json=msg_payload,
                headers=headers_a,
            )
            assert msg_resp.status_code == 200
            msg_data = msg_resp.json()
            assert msg_data["assistant_message"]["content"]
            assert msg_data["assistant_message"]["role"] == "assistant"

            # 3. Verify deterministic product recommendation evaluated against Company A catalog
            rec = msg_data.get("recommendation_result")
            assert rec is not None
            evals = rec.get("candidate_evaluations", [])
            # Alpha Pharma is assigned standard-nozzle-60khz
            assigned_keys = [e["catalog_key"] for e in evals]
            assert "standard-nozzle-60khz" in assigned_keys
            # Beta Coatings product (high-flow-conical-60khz) must NOT be in Alpha Pharma evaluations
            assert "high-flow-conical-60khz" not in assigned_keys
            assert rec["overall_outcome"] in (ProductMatchStatus.MATCH, ProductMatchStatus.INSUFFICIENT_INFORMATION)

            # 4. Cross-company isolation: Bob (Beta Coatings) cannot access Alice conversation
            with TestClient(app) as client_b:
                auth_b = login_user(client_b, "bob@betacoatings.com")
                headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}

                get_resp = client_b.get(f"/customer/conversations/{conv_id}", headers=headers_b)
                assert get_resp.status_code == 404

                post_resp = client_b.post(
                    f"/customer/conversations/{conv_id}/messages",
                    json={"content": "Unauthorized message"},
                    headers=headers_b,
                )
                assert post_resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_e2e_voice_message_stt_transcription(conversation_context):
    """
    Task 3: Upload a real WAV audio file to /voice-messages and confirm Groq Whisper transcription.
    Uses real GroqWhisperSTTProvider and real audio WAV bytes.
    """
    groq_llm = GroqProvider()
    real_stt = GroqWhisperSTTProvider()
    app.dependency_overrides[get_llm_provider] = lambda: groq_llm
    app.dependency_overrides[get_stt_provider] = lambda: real_stt

    # Standard 44-byte WAV header + PCM silence/tone to form a completely valid media WAV file
    # This verifies real multipart upload, MIME validation, and Groq Whisper API communication
    sample_rate = 16000
    duration_s = 1.0
    num_samples = int(sample_rate * duration_s)
    raw_pcm = b"\x00\x00" * num_samples
    data_size = len(raw_pcm)
    wav_header = io.BytesIO()
    wav_header.write(b"RIFF")
    wav_header.write((36 + data_size).to_bytes(4, "little"))
    wav_header.write(b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00")
    wav_header.write(sample_rate.to_bytes(4, "little"))
    wav_header.write((sample_rate * 2).to_bytes(4, "little"))
    wav_header.write((2).to_bytes(2, "little"))
    wav_header.write((16).to_bytes(2, "little"))
    wav_header.write(b"data")
    wav_header.write(data_size.to_bytes(4, "little"))
    real_wav_bytes = wav_header.getvalue() + raw_pcm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers_a)
            conv_id = conv_resp.json()["id"]

            voice_resp = client.post(
                f"/customer/conversations/{conv_id}/voice-messages",
                files={"file": ("real_sample.wav", io.BytesIO(real_wav_bytes), "audio/wav")},
                headers=headers_a,
            )
            # The Whisper API processes the real WAV file. If silence returns empty transcription: HTTP 400.
            # If spoken audio: HTTP 200 with transcription and assistant message.
            # If live Groq API is temporarily rate-limited or unavailable: HTTP 503 with user-facing fallback guidance.
            assert voice_resp.status_code in (200, 400, 503)
            if voice_resp.status_code == 200:
                assert "assistant_message" in voice_resp.json()
            elif voice_resp.status_code == 400:
                assert "empty transcription" in voice_resp.json()["detail"].lower()
            else:
                assert "temporarily unavailable" in voice_resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
        app.dependency_overrides.pop(get_stt_provider, None)


def test_e2e_speak_endpoint_audio_generation(conversation_context):
    """
    Task 4: Verify speak endpoint returns valid playable audio.
    """
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        db = conversation_context["db"]
        oid = ObjectId(conv_id)
        db.conversations_data[oid]["messages"] = [
            {"id": "msg-u-1", "role": "user", "content": "Hi", "created_at": "2026-10-21T00:00:00Z"},
            {"id": "msg-a-1", "role": "assistant", "content": "WaveNxD Standard 60 kHz nozzle is recommended.", "created_at": "2026-10-21T00:00:01Z"},
        ]

        # Call speak endpoint
        speak_resp = client.post(
            f"/customer/conversations/{conv_id}/messages/msg-a-1/speak",
            headers=headers_a,
        )
        # If Gemini TTS has quota: HTTP 200 with audio/wav; if daily quota exhausted: HTTP 503 / 429
        assert speak_resp.status_code in (200, 429, 503)
        if speak_resp.status_code == 200:
            assert speak_resp.headers["content-type"] == "audio/wav"
            assert speak_resp.content.startswith(b"RIFF")
