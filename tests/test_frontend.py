import io
from bson import ObjectId
import pytest
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.services.llm_provider import LLMResponse, get_llm_provider
from app.services.voice_service import get_stt_provider, get_tts_provider
from tests.test_conversations import conversation_context, login_user


class MockFrontendLLM:
    @property
    def provider_id(self):
        return "mock-frontend-llm"

    async def generate_chat_response(self, messages, system_prompt=None, correlation_id=None):
        return LLMResponse(
            content="For your 3 ml/min flow rate, we recommend the WaveNxD Standard 60 kHz Nozzle. ```json\n{\"requirements_update\": {\"application\": \"spray drying\", \"flow_rate_ml_min\": 3.0, \"viscosity_cp\": 20.0}}\n```",
            model="mock-frontend-llm",
        )


class MockFrontendSTT:
    async def transcribe_audio(self, audio_bytes, filename, content_type, language=None):
        return "We need an ultrasonic nozzle for laboratory spray drying at 3 ml/min and 20 cP viscosity."


class MockFrontendTTS:
    @property
    def supported_languages(self):
        return ["en", "hi", "mr"]

    async def synthesize_speech(self, text, language="en"):
        # Returns 44-byte WAV header + silence
        fake_wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        return fake_wav, "audio/wav"


def test_frontend_routes_served_successfully():
    """Verifies that the static index.html and assets are served at root, /login, /app and /static."""
    with TestClient(app) as client:
        # 1. Root route
        root_resp = client.get("/")
        assert root_resp.status_code == 200
        assert "text/html" in root_resp.headers["content-type"]
        assert "WaveNxD" in root_resp.text
        assert "loginView" in root_resp.text
        assert "workspaceView" in root_resp.text
        assert "specPanel" in root_resp.text

        # 2. Login route
        login_resp = client.get("/login")
        assert login_resp.status_code == 200
        assert "WaveNxD B2B Portal" in login_resp.text

        # 3. App route
        app_resp = client.get("/app")
        assert app_resp.status_code == 200
        assert "messagesContainer" in app_resp.text

        # 4. CSS static asset
        css_resp = client.get("/static/css/style.css")
        assert css_resp.status_code == 200
        assert "text/css" in css_resp.headers["content-type"]
        assert "--accent-cyan" in css_resp.text

        # 5. JS static asset
        js_resp = client.get("/static/js/app.js")
        assert js_resp.status_code == 200
        assert "javascript" in js_resp.headers["content-type"]
        assert "wavenxdPlayAudio" in js_resp.text


def test_all_imported_css_and_js_assets_resolve():
    """
    Regression test ensuring every modular stylesheet imported by style.css (such as tokens.css)
    and admin.css resolves with HTTP 200, correct MIME types, and is not accidentally gitignored.
    """
    import re
    from pathlib import Path

    with TestClient(app) as client:
        # 1. Verify style.css and every imported modular stylesheet
        root_css = client.get("/static/css/style.css")
        assert root_css.status_code == 200
        import_matches = re.findall(r'@import\s+["\']\.?/?([^"\']+)["\'];', root_css.text)
        assert len(import_matches) >= 10, "Expected at least 10 imported modular CSS files"
        assert "tokens.css" in import_matches, "tokens.css must be explicitly imported by style.css"

        for imported_file in import_matches:
            resp = client.get(f"/static/css/{imported_file}")
            assert resp.status_code == 200, f"Imported stylesheet /static/css/{imported_file} returned {resp.status_code}"
            assert "text/css" in resp.headers["content-type"], f"Invalid MIME for /static/css/{imported_file}"
            assert len(resp.text.strip()) > 50, f"Stylesheet /static/css/{imported_file} is suspiciously empty"

        # 2. Specifically verify tokens.css content
        tokens_resp = client.get("/static/css/tokens.css")
        assert tokens_resp.status_code == 200
        assert "--font-sans" in tokens_resp.text
        assert "--bg-main" in tokens_resp.text
        assert "--brand-blue" in tokens_resp.text
        assert "--radius-md" in tokens_resp.text

        # 3. Verify admin.css resolves
        admin_css = client.get("/static/css/admin.css")
        assert admin_css.status_code == 200
        assert "text/css" in admin_css.headers["content-type"]

        # 4. Verify core JS modules resolve
        for js_path in [
            "/static/js/app.js",
            "/static/js/admin.js",
            "/static/js/core/auth.js",
            "/static/js/core/state.js",
            "/static/js/core/api.js",
            "/static/js/customer/leads.js",
            "/static/js/admin/leads.js",
        ]:
            resp = client.get(js_path)
            assert resp.status_code == 200, f"Core JS module {js_path} returned {resp.status_code}"
            assert "javascript" in resp.headers["content-type"]

        # 5. Verify .gitignore does not ignore app/static/css/tokens.css
        gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
        if gitignore_path.exists():
            lines = [line.strip() for line in gitignore_path.read_text().splitlines()]
            assert "*token*" not in lines, "Broad '*token*' line in .gitignore breaks tokens.css"
            assert "*secret*" not in lines, "Broad '*secret*' line in .gitignore breaks secrets"


def test_frontend_full_customer_interaction_flow(conversation_context):
    """
    End-to-End integration test simulating the exact browser workflow:
    1. Obtains CSRF token (/auth/csrf)
    2. Logs in customer user (/auth/login)
    3. Verifies authenticated profile (/auth/me)
    4. Retrieves assigned products for customer's company (/customer/products)
    5. Creates a new consultation (/customer/conversations)
    6. Sends requirement message and verifies assistant recommendation (/customer/conversations/{id}/messages)
    7. Sends a voice message (/customer/conversations/{id}/voice-messages)
    8. Synthesizes speech for assistant message (/customer/conversations/{id}/messages/{msg_id}/speak)
    9. Logs out (/auth/logout)
    """
    mock_llm = MockFrontendLLM()
    mock_stt = MockFrontendSTT()
    mock_tts = MockFrontendTTS()

    app.dependency_overrides[get_llm_provider] = lambda: mock_llm
    app.dependency_overrides[get_stt_provider] = lambda: mock_stt
    app.dependency_overrides[get_tts_provider] = lambda: mock_tts

    try:
        with TestClient(app) as client:
            # Step 1: CSRF Initialization
            csrf_resp = client.get("/auth/csrf")
            assert csrf_resp.status_code == 200
            csrf_token = csrf_resp.json()["csrf_token"]
            assert csrf_token is not None

            # Step 2: Login as Alice (Alpha Pharma)
            login_resp = client.post(
                "/auth/login",
                json={"email": "alice@alphapharma.com", "password": "ValidCustPass123!"},
                headers={"X-CSRF-Token": csrf_token},
            )
            assert login_resp.status_code == 200
            login_data = login_resp.json()
            assert login_data["user"]["email"] == "alice@alphapharma.com"
            active_csrf = login_data["csrf_token"]

            # Step 3: Current User Profile
            me_resp = client.get("/auth/me")
            assert me_resp.status_code == 200
            assert me_resp.json()["email"] == "alice@alphapharma.com"

            # Step 4: Company Assigned Products
            prods_resp = client.get("/customer/products")
            assert prods_resp.status_code == 200
            products = prods_resp.json()
            catalog_keys = [p["catalog_key"] for p in products]
            # Standard 60kHz is assigned to Alpha Pharma
            assert "standard-nozzle-60khz" in catalog_keys
            # High flow conical 60kHz is assigned to Beta Coatings only
            assert "high-flow-conical-60khz" not in catalog_keys

            # Step 5: Create Conversation
            conv_resp = client.post(
                "/customer/conversations",
                json={"title": "Lab Atomization Consultation"},
                headers={"X-CSRF-Token": active_csrf},
            )
            assert conv_resp.status_code == 201
            conv_id = conv_resp.json()["id"]

            # Step 6: Send Text Message
            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "We require spray drying at 3 ml/min with 20 cP viscosity."},
                headers={"X-CSRF-Token": active_csrf},
            )
            assert msg_resp.status_code == 200
            msg_data = msg_resp.json()
            assert msg_data["assistant_message"]["content"]
            assistant_msg_id = msg_data["assistant_message"]["id"]

            # Verify deterministic recommendations in response
            rec = msg_data["recommendation_result"]
            assert rec is not None
            assert rec["overall_outcome"] == ProductMatchStatus.MATCH
            assert any(e["catalog_key"] == "standard-nozzle-60khz" for e in rec["candidate_evaluations"])

            # Step 7: Send Voice Message (Audio upload)
            fake_wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
            voice_resp = client.post(
                f"/customer/conversations/{conv_id}/voice-messages",
                files={"file": ("recording.wav", io.BytesIO(fake_wav), "audio/wav")},
                headers={"X-CSRF-Token": active_csrf},
            )
            assert voice_resp.status_code == 200
            voice_data = voice_resp.json()
            assert voice_data["user_message"]["input_modality"] == "voice"
            assert "laboratory spray drying" in voice_data["user_message"]["content"].lower()

            # Step 8: Audio Playback (Speak Endpoint)
            speak_resp = client.post(
                f"/customer/conversations/{conv_id}/messages/{assistant_msg_id}/speak",
                headers={"X-CSRF-Token": active_csrf},
            )
            assert speak_resp.status_code == 200
            assert speak_resp.headers["content-type"] == "audio/wav"
            assert speak_resp.content.startswith(b"RIFF")

            # Step 9: Logout
            logout_resp = client.post(
                "/auth/logout",
                headers={"X-CSRF-Token": active_csrf},
            )
            assert logout_resp.status_code == 200

            # Step 10: Verify unauthenticated after logout
            me_after = client.get("/auth/me")
            assert me_after.status_code == 401
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
        app.dependency_overrides.pop(get_stt_provider, None)
        app.dependency_overrides.pop(get_tts_provider, None)
