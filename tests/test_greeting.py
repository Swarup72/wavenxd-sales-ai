import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_provider import get_llm_provider
from tests.test_conversations import MockLLM, conversation_context, login_user


def test_new_conversation_has_initial_assistant_greeting(conversation_context):
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # Create conversation
        resp = client.post(
            "/customer/conversations",
            json={"title": "Greeting Test Consultation", "preferred_language": "en"},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        conv_id = data["id"]
        assert len(data["messages"]) == 1

        greeting = data["messages"][0]
        assert greeting["role"] == "assistant"
        assert "WaveNxD" in greeting["content"]
        assert "ultrasonic" in greeting["content"].lower()
        assert "liquid" in greeting["content"].lower() or "material" in greeting["content"].lower()
        assert greeting["language"] == "en"

        # Fetch conversation again to verify no duplication
        get_resp = client.get(f"/customer/conversations/{conv_id}", headers=headers)
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert len(get_data["messages"]) == 1
        assert get_data["messages"][0]["id"] == greeting["id"]


def test_greeting_multilingual_support(conversation_context):
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # Hindi greeting
        hi_resp = client.post(
            "/customer/conversations",
            json={"preferred_language": "hi"},
            headers=headers,
        )
        assert hi_resp.status_code == 201
        hi_greeting = hi_resp.json()["messages"][0]
        assert hi_greeting["role"] == "assistant"
        assert "नमस्ते" in hi_greeting["content"]
        assert "WaveNxD" in hi_greeting["content"]

        # Marathi greeting
        mr_resp = client.post(
            "/customer/conversations",
            json={"preferred_language": "mr"},
            headers=headers,
        )
        assert mr_resp.status_code == 201
        mr_greeting = mr_resp.json()["messages"][0]
        assert mr_greeting["role"] == "assistant"
        assert "नमस्कार" in mr_greeting["content"]
        assert "WaveNxD" in mr_greeting["content"]


def test_first_message_continues_conversation_with_greeting_context(conversation_context):
    mock_llm = MockLLM()
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth["csrf_token"]}

            # 1. Create conversation with initial greeting
            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]
            assert len(conv_resp.json()["messages"]) == 1

            # 2. Send user message
            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "We need spray drying with 5 ml/min flow rate and 15 cP viscosity."},
                headers=headers,
            )
            assert msg_resp.status_code == 200
            msg_data = msg_resp.json()

            # Verify response contains user message and assistant reply
            assert msg_data["user_message"]["content"] == "We need spray drying with 5 ml/min flow rate and 15 cP viscosity."
            assert msg_data["assistant_message"]["role"] == "assistant"

            # 3. Retrieve detail; now has 3 messages (greeting, user, assistant)
            detail_resp = client.get(f"/customer/conversations/{conv_id}", headers=headers)
            detail = detail_resp.json()
            assert len(detail["messages"]) == 3
            assert detail["messages"][0]["role"] == "assistant"
            assert detail["messages"][1]["role"] == "user"
            assert detail["messages"][2]["role"] == "assistant"

            # Verify requirements were extracted
            assert detail["requirements"]["flow_rate_ml_min"] == 5.0
            assert detail["requirements"]["viscosity_cp"] == 15.0
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
