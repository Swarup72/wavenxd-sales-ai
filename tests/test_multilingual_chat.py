import pytest
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.services.conversation_service import (
    detect_language,
    extract_regex_requirements,
)
from app.services.llm_provider import LLMProvider, LLMResponse, get_llm_provider
from tests.test_conversations import conversation_context, login_user


# --- Language Detection Unit Tests ---

def test_detect_language_variants():
    # English
    assert detect_language("We need an ultrasonic nozzle for precision coating.") == "en"

    # Hindi (Devanagari with Hindi vocabulary)
    assert detect_language("नमस्ते, हमें दवा कोटिंग के लिए स्प्रे नोजल चाहिए।") == "hi"

    # Marathi (Devanagari with Marathi vocabulary)
    assert detect_language("नमस्कार, आम्हाला लॅब स्प्रे ड्रायिंगसाठी नोझल पाहिजे आहे.") == "mr"

    # Hinglish
    assert detect_language("Hume lab spray drying ke liye nozzle chahiye flow rate kitna hoga?") == "hinglish"
    assert detect_language("hamara viscosity 20 cP hai aur spray chahiye") == "hinglish"


# --- Deterministic Parameter Extraction Across Languages ---

def test_extract_regex_requirements_multilingual():
    # English
    en_res = extract_regex_requirements("Viscosity is 25 cP, flow rate is 3.5 ml/min, droplet size is 40 um.")
    assert en_res["viscosity_cp"] == 25.0
    assert en_res["flow_rate_ml_min"] == 3.5
    assert en_res["droplet_size_um"] == 40.0

    # Hindi
    hi_res = extract_regex_requirements("द्रव की विस्कोसिटी 20 cP और फ्लो रेट 4.0 ml/min है, 45 माइक्रोन ड्रॉपलेट।")
    assert hi_res["viscosity_cp"] == 20.0
    assert hi_res["flow_rate_ml_min"] == 4.0
    assert hi_res["droplet_size_um"] == 45.0

    # Marathi
    mr_res = extract_regex_requirements("व्हिस्कोसिटी 15 cP आणि फ्लो 2.5 ml/min आवश्यक आहे, 30 मायक्रॉन.")
    assert mr_res["viscosity_cp"] == 15.0
    assert mr_res["flow_rate_ml_min"] == 2.5
    assert mr_res["droplet_size_um"] == 30.0

    # Hinglish
    hng_res = extract_regex_requirements("Fluid ka viscosity 18 cP hai aur flow 5.0 ml/min chahiye.")
    assert hng_res["viscosity_cp"] == 18.0
    assert hng_res["flow_rate_ml_min"] == 5.0


# --- Multilingual Conversation API End-to-End Tests ---

class MockMultilingualLLM(LLMProvider):
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_system_prompt: str | None = None
        self.last_messages: list[dict[str, str]] = []

    async def generate_chat_response(self, messages, system_prompt=None):
        self.last_system_prompt = system_prompt
        self.last_messages = messages
        return LLMResponse(content=self.response_text, model="mock-multilingual-llm")


def test_hindi_conversation_and_technical_preservation(conversation_context):
    mock_response = """नमस्ते! आपके लैब स्प्रे ड्राइंग (lab spray drying) के लिए हमारा Standard Ultrasonic Nozzle 60kHz पूरी तरह उपयुक्त है।
यह 5 ml/min तक का फ्लो रेट और 50 cP तक की विस्कोसिटी संभाल सकता है। इसका ऑपरेटिंग फ्रीक्वेंसी 60 kHz और ड्रॉपलेट साइज 40 µm है।

```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "flow_rate_ml_min": 3.0,
    "viscosity_cp": 20.0
  },
  "unresolved_questions": [],
  "detected_language": "hi"
}
```"""
    mock_llm = MockMultilingualLLM(mock_response)
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # User sends Hindi message
            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "नमस्ते, हमें लैब स्प्रे ड्राइंग के लिए 3.0 ml/min फ्लो और 20 cP विस्कोसिटी का नोजल चाहिए।"},
                headers=headers,
            )
            assert msg_resp.status_code == 200
            data = msg_resp.json()

            # Verify prompt instructions received language 'hi'
            assert "preferred language is 'hi'" in mock_llm.last_system_prompt

            # Verify assistant content preserves exact product name and units
            assistant_text = data["assistant_message"]["content"]
            assert "Standard Ultrasonic Nozzle 60kHz" in assistant_text
            assert "60 kHz" in assistant_text
            assert "40 µm" in assistant_text
            assert "5 ml/min" in assistant_text

            # Verify requirement extraction
            reqs = data["updated_requirements"]
            assert reqs["application"] == "Lab spray drying"
            assert reqs["flow_rate_ml_min"] == 3.0
            assert reqs["viscosity_cp"] == 20.0

            # Verify recommendation result
            assert data["recommendation_result"]["overall_outcome"] == ProductMatchStatus.MATCH
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_marathi_conversation_and_preference_update(conversation_context):
    mock_response = """नमस्कार! तुमच्या लॅब स्प्रे ड्रायिंगसाठी Standard Ultrasonic Nozzle 60kHz हा योग्य पर्याय आहे.
हा नोझल 5 ml/min फ्लो रेट आणि 50 cP पर्यंतची व्हिस्कोसिटी हाताळतो.

```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "flow_rate_ml_min": 2.0,
    "viscosity_cp": 15.0
  },
  "unresolved_questions": [],
  "detected_language": "mr"
}
```"""
    mock_llm = MockMultilingualLLM(mock_response)
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            # Create conversation with explicit preferred_language='mr'
            conv_resp = client.post(
                "/customer/conversations",
                json={"title": "Marathi Consultation", "preferred_language": "mr"},
                headers=headers,
            )
            assert conv_resp.status_code == 201
            assert conv_resp.json()["preferred_language"] == "mr"
            conv_id = conv_resp.json()["id"]

            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "आम्हाला लॅब स्प्रे ड्रायिंगसाठी 2.0 ml/min आणि 15 cP क्षमतेचा नोझल पाहिजे."},
                headers=headers,
            )
            assert msg_resp.status_code == 200
            data = msg_resp.json()

            # Product names and units preserved
            assert "Standard Ultrasonic Nozzle 60kHz" in data["assistant_message"]["content"]
            assert "5 ml/min" in data["assistant_message"]["content"]

            # Conversation preferred language is Marathi
            detail = client.get(f"/customer/conversations/{conv_id}").json()
            assert detail["preferred_language"] == "mr"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_hinglish_conversation_and_explicit_switch(conversation_context):
    mock_response = """Haan bilkul! Lab spray drying ke liye humara Standard Ultrasonic Nozzle 60kHz perfectly suited hai.
Ye 5 ml/min flow rate aur 50 cP viscosity tak handle karta hai.

```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "flow_rate_ml_min": 3.5,
    "viscosity_cp": 12.0
  },
  "unresolved_questions": []
}
```"""
    mock_llm = MockMultilingualLLM(mock_response)
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # 1. Send Hinglish message
            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Hume lab spray drying ke liye nozzle chahiye, viscosity 12 cP aur flow 3.5 ml/min."},
                headers=headers,
            )
            assert msg_resp.status_code == 200
            data = msg_resp.json()
            assert data["updated_requirements"]["viscosity_cp"] == 12.0
            assert data["updated_requirements"]["flow_rate_ml_min"] == 3.5

            # 2. Explicit switch of language to Hindi via payload
            client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Please explain in Hindi.", "language": "hi"},
                headers=headers,
            )
            assert "preferred language is 'hi'" in mock_llm.last_system_prompt
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
