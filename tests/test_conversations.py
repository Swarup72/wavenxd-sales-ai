from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.domain.enums import ConversationStatus, MessageRole, ProductMatchStatus, ProductStatus, UserRole
from app.main import app
from app.models.common import utc_now
from app.models.conversation import Conversation
from app.services.llm_provider import (
    LLMProvider,
    LLMProviderUnavailableError,
    LLMResponse,
    get_llm_provider,
)


class MockCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, key, direction=1):
        reverse = direction == -1
        self._items.sort(key=lambda x: x.get(key, 0), reverse=reverse)
        return self

    def limit(self, count):
        self._items = self._items[:count]
        return self

    async def to_list(self, length=None):
        if length is not None:
            return self._items[:length]
        return self._items


class MockConversationsDB:
    def __init__(self):
        self.users_data: dict[str, dict] = {}
        self.sessions_data: dict[str, dict] = {}
        self.companies_data: dict[ObjectId, dict] = {}
        self.products_data: dict[ObjectId, dict] = {}
        self.assignments_data: dict[tuple[ObjectId, ObjectId], dict] = {}
        self.conversations_data: dict[ObjectId, dict] = {}
        self.leads_data: dict[ObjectId, dict] = {}
        self.audit_logs_data: list[dict] = []
        self.command = AsyncMock(return_value={"ok": 1.0})

    @property
    def users(self):
        col = MagicMock()

        async def find_one(filter_dict):
            if "_id" in filter_dict:
                for u in self.users_data.values():
                    if u["_id"] == filter_dict["_id"]:
                        return u
                return None
            if "email" in filter_dict:
                return self.users_data.get(filter_dict["email"])
            return None

        col.find_one = AsyncMock(side_effect=find_one)
        return col

    @property
    def sessions(self):
        col = MagicMock()

        async def find_one(filter_dict):
            th = filter_dict.get("session_token_hash")
            return self.sessions_data.get(th)

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.sessions_data[d["session_token_hash"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            th = filter_dict.get("session_token_hash")
            doc = self.sessions_data.get(th)
            res = MagicMock()
            if doc:
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                res.modified_count = 1
            else:
                res.modified_count = 0
            return res

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        return col

    @property
    def companies(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            return self.companies_data.get(cid)

        col.find_one = AsyncMock(side_effect=find_one)
        return col

    @property
    def products(self):
        col = MagicMock()

        async def find_one(filter_dict):
            pid = filter_dict.get("_id")
            return self.products_data.get(pid)

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for p in self.products_data.values():
                if "_id" in filter_dict and isinstance(filter_dict["_id"], dict) and "$in" in filter_dict["_id"]:
                    if p["_id"] not in filter_dict["_id"]["$in"]:
                        continue
                if "status" in filter_dict and p.get("status") != filter_dict["status"]:
                    continue
                if filter_dict.get("technical_review_required") is False and p.get("technical_review_required", False):
                    continue
                items.append(p)
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        return col

    @property
    def customer_product_assignments(self):
        col = MagicMock()

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for (cid, pid), a in self.assignments_data.items():
                if "company_id" in filter_dict and cid != filter_dict["company_id"]:
                    continue
                if "product_id" in filter_dict and pid != filter_dict["product_id"]:
                    continue
                if "is_active" in filter_dict and a.get("is_active") != filter_dict["is_active"]:
                    continue
                items.append(a)
            return MockCursor(items)

        col.find = MagicMock(side_effect=find)
        return col

    @property
    def conversations(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            if cid:
                return self.conversations_data.get(cid)
            for c in self.conversations_data.values():
                match = True
                for k, v in filter_dict.items():
                    if c.get(k) != v:
                        match = False
                        break
                if match:
                    return c
            return None

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for c in self.conversations_data.values():
                match = True
                for k, v in filter_dict.items():
                    if c.get(k) != v:
                        match = False
                        break
                if match:
                    items.append(c)
            return MockCursor(items)

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.conversations_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            cid = filter_dict.get("_id")
            doc = self.conversations_data.get(cid)
            res = MagicMock()
            if doc:
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                res.modified_count = 1
            else:
                res.modified_count = 0
            return res

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        return col

    @property
    def leads(self):
        col = MagicMock()

        async def find_one(filter_dict):
            lid = filter_dict.get("_id")
            if lid:
                return self.leads_data.get(lid)
            for ld in self.leads_data.values():
                match = True
                for k, v in filter_dict.items():
                    if ld.get(k) != v:
                        match = False
                        break
                if match:
                    return ld
            return None

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for ld in self.leads_data.values():
                match = True
                for k, v in filter_dict.items():
                    if ld.get(k) != v:
                        match = False
                        break
                if match:
                    items.append(ld)
            return MockCursor(items)

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.leads_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            lid = filter_dict.get("_id")
            doc = self.leads_data.get(lid)
            res = MagicMock()
            if doc:
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                res.modified_count = 1
            else:
                res.modified_count = 0
            return res

        async def replace_one(filter_dict, doc):
            lid = filter_dict.get("_id")
            d = dict(doc)
            d["_id"] = lid
            self.leads_data[lid] = d
            res = MagicMock()
            res.modified_count = 1
            return res

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.replace_one = AsyncMock(side_effect=replace_one)
        return col

    @property
    def audit_logs(self):
        col = MagicMock()

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.audit_logs_data.append(d)
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        def find(filter_dict=None):
            return MockCursor(list(self.audit_logs_data))

        col.insert_one = AsyncMock(side_effect=insert_one)
        col.find = MagicMock(side_effect=find)
        return col


class MockLLM(LLMProvider):
    def __init__(self, response_text: str = "Assistant reply"):
        self.response_text = response_text
        self.last_messages: list[dict[str, str]] = []
        self.last_system_prompt: str | None = None

    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.last_messages = messages
        self.last_system_prompt = system_prompt
        return LLMResponse(content=self.response_text, model="mock-model")


@pytest.fixture
def conversation_context():
    db = MockConversationsDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    admin_id = ObjectId()
    alice_id = ObjectId()
    bob_id = ObjectId()
    company_a = ObjectId()
    company_b = ObjectId()

    db.companies_data[company_a] = {
        "_id": company_a,
        "name": "Alpha Pharma Ltd",
        "is_active": True,
    }
    db.companies_data[company_b] = {
        "_id": company_b,
        "name": "Beta Coatings Inc",
        "is_active": True,
    }

    db.users_data["admin@wavenxd.com"] = {
        "_id": admin_id,
        "email": "admin@wavenxd.com",
        "full_name": "Admin Supervisor",
        "role": UserRole.ADMIN,
        "company_id": None,
        "password_hash": hash_password("ValidAdminPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["alice@alphapharma.com"] = {
        "_id": alice_id,
        "email": "alice@alphapharma.com",
        "full_name": "Dr. Alice",
        "role": UserRole.CUSTOMER,
        "company_id": company_a,
        "password_hash": hash_password("ValidCustPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["bob@betacoatings.com"] = {
        "_id": bob_id,
        "email": "bob@betacoatings.com",
        "full_name": "Bob Builder",
        "role": UserRole.CUSTOMER,
        "company_id": company_b,
        "password_hash": hash_password("ValidCustPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    # Products
    p_std_60k = ObjectId()
    p_high_flow = ObjectId()
    p_draft = ObjectId()

    db.products_data[p_std_60k] = {
        "_id": p_std_60k,
        "name": "Standard Ultrasonic Nozzle 60kHz",
        "catalog_key": "standard-nozzle-60khz",
        "category": "ultrasonic_nozzle",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Lab spray drying"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
    }

    db.products_data[p_high_flow] = {
        "_id": p_high_flow,
        "name": "High-Flow Conical Ultrasonic Nozzle - 60 kHz",
        "catalog_key": "high-flow-conical-60khz",
        "category": "ultrasonic_nozzle",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_max_ml_min": 200.0,
        "flow_rate_description": "up to 200 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Industrial spray drying"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
    }

    db.products_data[p_draft] = {
        "_id": p_draft,
        "name": "180kHz Stent Coating Nozzle",
        "catalog_key": "standard-nozzle-torch-180khz",
        "category": "ultrasonic_nozzle",
        "status": ProductStatus.DRAFT,
        "technical_review_required": True,
        "applications": ["Stent coatings"],
    }

    # Company A is assigned standard-nozzle-60khz and the draft nozzle
    db.assignments_data[(company_a, p_std_60k)] = {
        "_id": ObjectId(),
        "company_id": company_a,
        "product_id": p_std_60k,
        "is_active": True,
    }
    db.assignments_data[(company_a, p_draft)] = {
        "_id": ObjectId(),
        "company_id": company_a,
        "product_id": p_draft,
        "is_active": True,
    }

    # Company B is assigned high-flow-conical-60khz
    db.assignments_data[(company_b, p_high_flow)] = {
        "_id": ObjectId(),
        "company_id": company_b,
        "product_id": p_high_flow,
        "is_active": True,
    }

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "db": db,
            "company_a": company_a,
            "company_b": company_b,
            "alice_id": alice_id,
            "bob_id": bob_id,
            "p_std_60k": p_std_60k,
            "p_high_flow": p_high_flow,
            "p_draft": p_draft,
        }


def login_user(client: TestClient, email: str) -> dict:
    csrf_resp = client.get("/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = client.post(
        "/auth/login",
        json={"email": email, "password": "ValidCustPass123!" if "admin" not in email else "ValidAdminPass123!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_resp.status_code == 200
    return {"csrf_token": login_resp.json()["csrf_token"]}


def test_conversation_creation_and_listing(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        # Create conversation
        resp = client.post(
            "/customer/conversations",
            json={"title": "Lab Atomization Project"},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Lab Atomization Project"
        assert data["company_id"] == str(conversation_context["company_a"])
        assert data["user_id"] == str(conversation_context["alice_id"])
        conv_id = data["id"]

        # List conversations
        list_resp = client.get("/customer/conversations")
        assert list_resp.status_code == 200
        conv_list = list_resp.json()
        assert len(conv_list) == 1
        assert conv_list[0]["id"] == conv_id
        assert conv_list[0]["message_count"] == 1

        # Retrieve specific conversation
        detail_resp = client.get(f"/customer/conversations/{conv_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["id"] == conv_id
        assert len(detail_data["messages"]) == 1
        assert detail_data["messages"][0]["role"] == "assistant"


def test_customer_conversation_isolation(conversation_context):
    conv_id = None
    with TestClient(app) as client_a:
        auth_a = login_user(client_a, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        resp = client_a.post(
            "/customer/conversations",
            json={"title": "Alice Private Conversation"},
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

    # Bob from Company B logs in
    with TestClient(app) as client_b:
        auth_b = login_user(client_b, "bob@betacoatings.com")
        headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}

        # 1. Bob cannot see Alice's conversation in his list
        list_resp = client_b.get("/customer/conversations")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 0

        # 2. Bob cannot retrieve Alice's conversation (returns 404 to prevent enumeration)
        get_resp = client_b.get(f"/customer/conversations/{conv_id}")
        assert get_resp.status_code == 404
        assert "not found" in get_resp.json()["detail"].lower()

        # 3. Bob cannot send messages to Alice's conversation
        msg_resp = client_b.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "Attempting cross-tenant injection"},
            headers=headers_b,
        )
        assert msg_resp.status_code == 404


def test_unauthenticated_and_wrong_role_access(conversation_context):
    with TestClient(app) as client:
        # Unauthenticated
        assert client.get("/customer/conversations").status_code == 401
        assert client.post("/customer/conversations", json={}).status_code == 401

        # Admin user denied from customer conversation endpoints
        login_user(client, "admin@wavenxd.com")
        assert client.get("/customer/conversations").status_code == 403
        assert client.post("/customer/conversations", json={}).status_code == 403


def test_malformed_conversation_id(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        bad_id = "invalid-oid-xyz"
        assert client.get(f"/customer/conversations/{bad_id}").status_code == 400
        assert client.post(
            f"/customer/conversations/{bad_id}/messages",
            json={"content": "Hello"},
            headers=headers,
        ).status_code == 400


def test_message_length_and_validation(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        # Create conversation
        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        # 1. Empty message content rejected
        empty_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "   "},
            headers=headers,
        )
        assert empty_resp.status_code in (400, 422)

        # 2. Exceeding max length (> 5000 chars) rejected
        long_content = "x" * 5001
        long_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": long_content},
            headers=headers,
        )
        assert long_resp.status_code in (400, 422)


def test_message_processing_and_requirement_extraction(conversation_context):
    mock_llm_response = """I recommend our Standard 60 kHz Ultrasonic Nozzle for your lab spray drying application.
It verified for flow rates up to 5 ml/min and viscosities below 50 cP.

```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "flow_rate_ml_min": 3.0,
    "viscosity_cp": 20.0
  },
  "unresolved_questions": ["What is your preferred droplet size?"]
}
```"""

    mock_llm = MockLLM(response_text=mock_llm_response)
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            msg_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "We need an ultrasonic nozzle for lab spray drying with 3.0 ml/min flow and 20 cP viscosity."},
                headers=headers,
            )
            assert msg_resp.status_code == 200
            data = msg_resp.json()

            # Assistant response has JSON stripped
            assert "Standard 60 kHz Ultrasonic Nozzle" in data["assistant_message"]["content"]
            assert "```json" not in data["assistant_message"]["content"]

            # Requirements successfully extracted and merged
            reqs = data["updated_requirements"]
            assert reqs["application"] == "Lab spray drying"
            assert reqs["flow_rate_ml_min"] == 3.0
            assert reqs["viscosity_cp"] == 20.0

            # Recommendation result was evaluated
            rec = data["recommendation_result"]
            assert rec is not None
            assert rec["overall_outcome"] == ProductMatchStatus.MATCH
            assert any(p["catalog_key"] == "standard-nozzle-60khz" for p in rec["confirmed_recommendations"])
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_updating_requirements_without_losing_unrelated_fields_and_corrections(conversation_context):
    mock_llm = MockLLM()
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # Step 1: Provide application and viscosity
            mock_llm.response_text = """Got it!
```json
{
  "requirements_update": {
    "application": "Lab spray drying",
    "viscosity_cp": 25.0
  }
}
```"""
            client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "We are working on lab spray drying with 25 cP fluid."},
                headers=headers,
            )

            # Step 2: Add flow rate without mentioning application or viscosity
            mock_llm.response_text = """Understood!
```json
{
  "requirements_update": {
    "flow_rate_ml_min": 2.5
  }
}
```"""
            resp2 = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Our required flow rate is 2.5 ml/min."},
                headers=headers,
            )
            reqs2 = resp2.json()["updated_requirements"]
            assert reqs2["application"] == "Lab spray drying"  # Preserved!
            assert reqs2["viscosity_cp"] == 25.0              # Preserved!
            assert reqs2["flow_rate_ml_min"] == 2.5          # Added!

            # Step 3: Explicit correction of viscosity from 25 to 15 cP
            mock_llm.response_text = """Updated your viscosity!
```json
{
  "requirements_update": {
    "viscosity_cp": 15.0
  }
}
```"""
            resp3 = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Actually, upon re-measurement the fluid viscosity is 15 cP."},
                headers=headers,
            )
            reqs3 = resp3.json()["updated_requirements"]
            assert reqs3["viscosity_cp"] == 15.0              # Explicitly corrected!
            assert reqs3["application"] == "Lab spray drying"  # Preserved!
            assert reqs3["flow_rate_ml_min"] == 2.5          # Preserved!
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_product_authorization_before_context_construction(conversation_context):
    mock_llm = MockLLM(response_text="Sure, I can assist.")
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "What nozzles do you offer?"},
                headers=headers,
            )

            prompt = mock_llm.last_system_prompt
            assert prompt is not None

            # 1. Company A's active published product IS in the LLM context
            assert "Standard Ultrasonic Nozzle 60kHz" in prompt

            # 2. Company A's DRAFT product (180 kHz stent nozzle) is STRICTLY EXCLUDED
            assert "180kHz Stent Coating Nozzle" not in prompt

            # 3. Company B's high-flow nozzle is STRICTLY EXCLUDED from Company A's context
            assert "High-Flow Conical Ultrasonic Nozzle" not in prompt
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_llm_timeout_and_provider_unavailable_returns_503(conversation_context):
    class TimeoutLLM(LLMProvider):
        async def generate_chat_response(self, messages, system_prompt=None):
            raise LLMProviderUnavailableError("Connection to Ollama timed out after 30s")

    app.dependency_overrides[get_llm_provider] = lambda: TimeoutLLM()

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Hello!"},
                headers=headers,
            )
            assert resp.status_code == 503
            assert "unavailable" in resp.json()["detail"].lower()

            # Ensure conversation messages were not partially corrupted; only the initial greeting is preserved
            detail = client.get(f"/customer/conversations/{conv_id}").json()
            assert len(detail["messages"]) == 1
            assert detail["messages"][0]["role"] == "assistant"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_real_ollama_provider_unreachable_returns_503(conversation_context, monkeypatch):
    # Ensure get_llm_provider is not overridden so real OllamaProvider is used
    app.dependency_overrides.pop(get_llm_provider, None)
    from app.core.config import get_settings
    # Configure Ollama provider and small timeout so connection attempt fails fast
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "llm_fallback_enabled", False)
    monkeypatch.setattr(settings, "ollama_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "ollama_base_url", "http://127.0.0.1:54321")

    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "Hello sales team!"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()


def test_malformed_llm_json_handled_safely(conversation_context):
    # LLM returns malformed JSON in code block
    mock_llm = MockLLM(response_text="I recommend our nozzle. ```json {broken json here")
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    try:
        with TestClient(app) as client:
            auth_a = login_user(client, "alice@alphapharma.com")
            headers = {"X-CSRF-Token": auth_a["csrf_token"]}

            conv_resp = client.post("/customer/conversations", headers=headers)
            conv_id = conv_resp.json()["id"]

            # User mentions viscosity directly -> regex backup extracts it even with broken LLM json
            resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Our fluid viscosity is 30 cP."},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["updated_requirements"]["viscosity_cp"] == 30.0
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_evaluate_conversation_recommendations_endpoint(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        # Pre-populate requirements on the conversation
        db = conversation_context["db"]
        oid = ObjectId(conv_id)
        db.conversations_data[oid]["requirements"] = {
            "application": "Lab spray drying",
            "flow_rate_ml_min": 2.0,
            "viscosity_cp": 10.0,
        }

        eval_resp = client.post(
            f"/customer/conversations/{conv_id}/recommendations",
            headers=headers,
        )
        assert eval_resp.status_code == 200
        data = eval_resp.json()
        assert data["overall_outcome"] == ProductMatchStatus.MATCH
        assert any(p["catalog_key"] == "standard-nozzle-60khz" for p in data["confirmed_recommendations"])
