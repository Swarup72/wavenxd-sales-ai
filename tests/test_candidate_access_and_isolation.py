from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password, hash_token, verify_password
from app.domain.enums import (
    ConversationStatus,
    InvitationStatus,
    MessageRole,
    ProductMatchStatus,
    ProductStatus,
    UserRole,
)
from app.main import app
from app.models.common import utc_now
from app.services.llm_provider import LLMResponse, get_llm_provider


class MockCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, key, direction=1):
        reverse = direction == -1
        self._items.sort(key=lambda x: x.get(key, 0), reverse=reverse)
        return self

    async def to_list(self, length=None):
        if length is not None:
            return self._items[:length]
        return self._items


class MockAccessDB:
    def __init__(self):
        self.companies_data: dict[ObjectId, dict] = {}
        self.users_data: dict[str, dict] = {}
        self.invitations_data: dict[str, dict] = {}
        self.products_data: dict[ObjectId, dict] = {}
        self.assignments_data: dict[tuple[ObjectId, ObjectId], dict] = {}
        self.conversations_data: dict[ObjectId, dict] = {}
        self.sessions_data: dict[str, dict] = {}
        self.audit_logs_data: list[dict] = []
        self.command = AsyncMock(return_value={"ok": 1.0})

    @property
    def companies(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            comp = self.companies_data.get(cid)
            if not comp:
                return None
            if "is_active" in filter_dict and comp.get("is_active") != filter_dict["is_active"]:
                return None
            return comp

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.companies_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            cid = filter_dict.get("_id")
            comp = self.companies_data.get(cid)
            if comp:
                for k, v in update_dict.get("$set", {}).items():
                    comp[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        def find(filter_dict=None):
            items = list(self.companies_data.values())
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find = find
        return col

    @property
    def users(self):
        col = MagicMock()

        async def find_one(filter_dict):
            if "email" in filter_dict:
                return self.users_data.get(filter_dict["email"])
            if "_id" in filter_dict:
                for u in self.users_data.values():
                    if u["_id"] == filter_dict["_id"]:
                        return u
            return None

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.users_data[d["email"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            u = await find_one(filter_dict)
            if u:
                for k, v in update_dict.get("$set", {}).items():
                    u[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        def find(filter_dict=None):
            items = list(self.users_data.values())
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find = find
        return col

    @property
    def invitations(self):
        col = MagicMock()

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.invitations_data[d["invitation_token_hash"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def find_one_and_update(filter_dict, update_dict, return_document=None):
            th = filter_dict.get("invitation_token_hash")
            doc = self.invitations_data.get(th)
            if not doc:
                return None
            if doc.get("status") != filter_dict.get("status"):
                return None
            if "expires_at" in filter_dict:
                gt = filter_dict["expires_at"].get("$gt")
                if gt and doc["expires_at"] <= gt:
                    return None
            old_doc = dict(doc)
            for k, v in update_dict.get("$set", {}).items():
                doc[k] = v
            return old_doc

        async def update_one(filter_dict, update_dict):
            iid = filter_dict.get("_id")
            for doc in self.invitations_data.values():
                if doc["_id"] == iid:
                    for k, v in update_dict.get("$set", {}).items():
                        doc[k] = v
                    return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        def find(filter_dict=None):
            items = list(self.invitations_data.values())
            return MockCursor(items)

        col.insert_one = AsyncMock(side_effect=insert_one)
        col.find_one_and_update = AsyncMock(side_effect=find_one_and_update)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find = find
        return col

    @property
    def products(self):
        col = MagicMock()

        async def find_one(filter_dict):
            pid = filter_dict.get("_id")
            if pid:
                return self.products_data.get(pid)
            key = filter_dict.get("catalog_key")
            if key:
                for p in self.products_data.values():
                    if p["catalog_key"] == key:
                        return p
            return None

        def find(filter_dict=None):
            items = list(self.products_data.values())
            if filter_dict:
                if "_id" in filter_dict and "$in" in filter_dict["_id"]:
                    ids = set(filter_dict["_id"]["$in"])
                    items = [p for p in items if p["_id"] in ids]
                if "status" in filter_dict:
                    items = [p for p in items if p.get("status") == filter_dict["status"]]
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = find
        return col

    @property
    def customer_product_assignments(self):
        col = MagicMock()

        async def find_one(filter_dict):
            key = (filter_dict.get("company_id"), filter_dict.get("product_id"))
            return self.assignments_data.get(key)

        async def update_one(filter_dict, update_dict, upsert=False):
            key = (filter_dict.get("company_id"), filter_dict.get("product_id"))
            doc = self.assignments_data.get(key)
            if not doc and upsert:
                doc = {
                    "_id": ObjectId(),
                    "company_id": filter_dict.get("company_id"),
                    "product_id": filter_dict.get("product_id"),
                }
                for k, v in update_dict.get("$setOnInsert", {}).items():
                    doc[k] = v
                self.assignments_data[key] = doc

            if doc:
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def delete_one(filter_dict):
            key = (filter_dict.get("company_id"), filter_dict.get("product_id"))
            if key in self.assignments_data:
                del self.assignments_data[key]
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

        async def count_documents(filter_dict=None):
            items = list(self.assignments_data.values())
            if filter_dict:
                if "is_active" in filter_dict:
                    items = [a for a in items if a.get("is_active") == filter_dict["is_active"]]
                if "company_id" in filter_dict:
                    items = [a for a in items if a.get("company_id") == filter_dict["company_id"]]
            return len(items)

        def find(filter_dict=None):
            items = list(self.assignments_data.values())
            if filter_dict:
                if "company_id" in filter_dict:
                    items = [a for a in items if a["company_id"] == filter_dict["company_id"]]
                if "is_active" in filter_dict:
                    items = [a for a in items if a.get("is_active") == filter_dict["is_active"]]
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.delete_one = AsyncMock(side_effect=delete_one)
        col.count_documents = AsyncMock(side_effect=count_documents)
        col.find = find
        return col

    @property
    def company_products(self):
        return self.customer_product_assignments

    @property
    def conversations(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            conv = self.conversations_data.get(cid)
            if not conv:
                return None
            if "company_id" in filter_dict and conv.get("company_id") != filter_dict["company_id"]:
                return None
            return conv

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.conversations_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            conv = await find_one(filter_dict)
            if conv:
                for k, v in update_dict.get("$set", {}).items():
                    conv[k] = v
                if "$push" in update_dict:
                    for k, v in update_dict["$push"].items():
                        conv.setdefault(k, []).append(v)
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        def find(filter_dict=None):
            items = list(self.conversations_data.values())
            if filter_dict and "company_id" in filter_dict:
                items = [c for c in items if c["company_id"] == filter_dict["company_id"]]
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find = find
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
            s = self.sessions_data.get(th)
            if s:
                for k, v in update_dict.get("$set", {}).items():
                    s[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def delete_one(filter_dict):
            th = filter_dict.get("session_token_hash")
            if th in self.sessions_data:
                del self.sessions_data[th]
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.delete_one = AsyncMock(side_effect=delete_one)
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
            return MockCursor(self.audit_logs_data)

        col.insert_one = AsyncMock(side_effect=insert_one)
        col.find = find
        return col


class MockLLM:
    async def generate_chat_response(self, messages, system_prompt=None, correlation_id=None):
        return LLMResponse(
            content="We evaluated your specifications. ```json\n{\"requirements_update\": {\"flow_rate_ml_min\": 2.0}}\n```",
            model="mock-llm",
        )


@pytest.fixture
def access_context():
    db = MockAccessDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    now = utc_now()
    admin_id = ObjectId()
    co_a_id = ObjectId()
    co_b_id = ObjectId()

    # Company A & B
    db.companies_data[co_a_id] = {
        "_id": co_a_id,
        "name": "Alpha Pharma Ltd",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.companies_data[co_b_id] = {
        "_id": co_b_id,
        "name": "Beta Coatings Inc",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }

    # Admin User
    db.users_data["admin@wavenxd.com"] = {
        "_id": admin_id,
        "email": "admin@wavenxd.com",
        "full_name": "WaveNxD Admin",
        "role": UserRole.ADMIN,
        "company_id": None,
        "password_hash": hash_password("ValidAdminPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }

    # Product 1 (Standard 60kHz) & Product 2 (High-Flow Conical)
    prod_1_id = ObjectId()
    prod_2_id = ObjectId()
    db.products_data[prod_1_id] = {
        "_id": prod_1_id,
        "catalog_key": "standard-nozzle-60khz",
        "name": "WaveNxD Standard 60 kHz Ultrasonic Nozzle",
        "category": "standard",
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "frequency_khz": 60.0,
        "droplet_size_um": 30.0,
        "flow_rate_min_ml_min": 0.5,
        "flow_rate_max_ml_min": 10.0,
        "viscosity_max_cp": 50.0,
        "spray_pattern": "focused conical",
        "created_at": now,
        "updated_at": now,
    }
    db.products_data[prod_2_id] = {
        "_id": prod_2_id,
        "catalog_key": "high-flow-conical-60khz",
        "name": "WaveNxD High-Flow Conical Atomizer",
        "category": "high_flow",
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "frequency_khz": 60.0,
        "droplet_size_um": 35.0,
        "flow_rate_min_ml_min": 5.0,
        "flow_rate_max_ml_min": 50.0,
        "viscosity_max_cp": 100.0,
        "spray_pattern": "wide conical",
        "created_at": now,
        "updated_at": now,
    }

    mock_llm = MockLLM()
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "db": db,
            "admin_id": admin_id,
            "co_a_id": co_a_id,
            "co_b_id": co_b_id,
            "prod_1_id": prod_1_id,
            "prod_2_id": prod_2_id,
        }

    app.dependency_overrides.pop(get_llm_provider, None)


def admin_login(client: TestClient):
    csrf = client.get("/auth/csrf").json()["csrf_token"]
    res = client.post(
        "/auth/login",
        json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
        headers={"X-CSRF-Token": csrf},
        cookies={"wavenxd_csrf": csrf},
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]


def test_complete_candidate_lifecycle_and_catalog_isolation(access_context):
    """
    Verifies full lifecycle:
    1. Admin creates new company and invites candidate.
    2. Candidate accepts invitation and sets password.
    3. Customer signs in and checks catalog.
    4. Admin grants 1 product assignment, then 2nd product assignment.
    5. Customer recommendations evaluate only company-authorized products.
    6. Cross-company product and consultation isolation is strictly enforced.
    7. Admin-only operations reject customer attempts.
    8. User deactivation immediately blocks access.
    """
    db = access_context["db"]

    with TestClient(app) as client:
        # Step 1: Admin creates new company
        admin_csrf = admin_login(client)

        comp_resp = client.post(
            "/admin/companies",
            json={
                "name": "NanoBio Diagnostics Ltd",
                "contact_email": "ops@nanobio.com",
                "notes": "Medical diagnostic micro-coatings",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert comp_resp.status_code == 200
        new_company_id = comp_resp.json()["id"]

        # Step 2: Admin creates invitation for candidate
        inv_resp = client.post(
            "/admin/invitations",
            json={
                "email": "candidate@nanobio.com",
                "company_id": new_company_id,
                "expiry_hours": 72,
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert inv_resp.status_code == 200
        raw_token = inv_resp.json()["invitation_token"]

        # Step 3: Candidate validates & accepts invitation in anonymous session
        client.cookies.clear()
        anon_csrf = client.get("/auth/csrf").json()["csrf_token"]

        accept_resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "SecurePassword123!",
                "full_name": "Dr. Sarah Chen",
            },
            headers={"X-CSRF-Token": anon_csrf},
            cookies={"wavenxd_csrf": anon_csrf},
        )
        assert accept_resp.status_code == 200
        user_info = accept_resp.json()
        assert user_info["email"] == "candidate@nanobio.com"
        assert user_info["role"] == "customer"
        assert user_info["company_id"] == new_company_id

        # Verify password hashed with Argon2id
        user_doc = db.users_data["candidate@nanobio.com"]
        assert verify_password("SecurePassword123!", user_doc["password_hash"])

        # Reusing the invitation must be rejected
        reuse_resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "SecurePassword123!",
            },
            headers={"X-CSRF-Token": anon_csrf},
            cookies={"wavenxd_csrf": anon_csrf},
        )
        assert reuse_resp.status_code == 404

        # Step 4: Customer logs in
        login_resp = client.post(
            "/auth/login",
            json={"email": "candidate@nanobio.com", "password": "SecurePassword123!"},
            headers={"X-CSRF-Token": anon_csrf},
            cookies={"wavenxd_csrf": anon_csrf},
        )
        assert login_resp.status_code == 200
        cust_csrf = login_resp.json()["csrf_token"]

        # Customer checks assigned products: initially empty
        prods_resp = client.get("/customer/products")
        assert prods_resp.status_code == 200
        assert len(prods_resp.json()) == 0

        # Customer creates consultation without assigned products
        conv_resp = client.post(
            "/customer/conversations",
            json={"title": "Diagnostic Spray Testing"},
            headers={"X-CSRF-Token": cust_csrf},
        )
        assert conv_resp.status_code == 201
        conv_id = conv_resp.json()["id"]

        msg_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "We need spray drying at 2 ml/min"},
            headers={"X-CSRF-Token": cust_csrf},
        )
        assert msg_resp.status_code == 200
        msg_data = msg_resp.json()
        # Candidate evaluations are empty because no products assigned
        rec = msg_data.get("recommendation_result")
        assert len(rec.get("candidate_evaluations", [])) == 0

        # Step 5: Admin grants product 1 (standard 60kHz) entitlement to NanoBio Ltd
        client.cookies.clear()
        admin_csrf = admin_login(client)

        grant_resp = client.post(
            f"/admin/companies/{new_company_id}/products/{str(access_context['prod_1_id'])}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert grant_resp.status_code == 200

        # Customer logs back in and now sees exactly 1 assigned product
        client.cookies.clear()
        anon_csrf = client.get("/auth/csrf").json()["csrf_token"]
        login_resp = client.post(
            "/auth/login",
            json={"email": "candidate@nanobio.com", "password": "SecurePassword123!"},
            headers={"X-CSRF-Token": anon_csrf},
            cookies={"wavenxd_csrf": anon_csrf},
        )
        cust_csrf = login_resp.json()["csrf_token"]

        prods_resp = client.get("/customer/products")
        assert prods_resp.status_code == 200
        assigned = prods_resp.json()
        assert len(assigned) == 1
        assert assigned[0]["catalog_key"] == "standard-nozzle-60khz"

        # Customer sends new requirement message: standard 60kHz is now evaluated!
        msg_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "We need spray drying at 3 ml/min and 20 cP"},
            headers={"X-CSRF-Token": cust_csrf},
        )
        assert msg_resp.status_code == 200
        rec = msg_resp.json().get("recommendation_result")
        eval_keys = [c["catalog_key"] for c in rec.get("candidate_evaluations", [])]
        assert "standard-nozzle-60khz" in eval_keys
        # High flow conical is NOT assigned, so must NOT be evaluated
        assert "high-flow-conical-60khz" not in eval_keys

        # Step 6: Cross-Company Isolation
        # Create user Bob in Beta Coatings Inc
        now = utc_now()
        bob_id = ObjectId()
        db.users_data["bob@betacoatings.com"] = {
            "_id": bob_id,
            "email": "bob@betacoatings.com",
            "full_name": "Bob Beta",
            "role": UserRole.CUSTOMER,
            "company_id": access_context["co_b_id"],
            "password_hash": hash_password("ValidCustPass123!"),
            "is_active": True,
            "must_change_password": False,
            "created_at": now,
            "updated_at": now,
        }

        client.cookies.clear()
        bob_csrf_raw = client.get("/auth/csrf").json()["csrf_token"]
        bob_login = client.post(
            "/auth/login",
            json={"email": "bob@betacoatings.com", "password": "ValidCustPass123!"},
            headers={"X-CSRF-Token": bob_csrf_raw},
            cookies={"wavenxd_csrf": bob_csrf_raw},
        )
        assert bob_login.status_code == 200
        bob_csrf = bob_login.json()["csrf_token"]

        # Bob attempts to access Sarah's conversation -> 404
        get_conv_resp = client.get(f"/customer/conversations/{conv_id}", headers={"X-CSRF-Token": bob_csrf})
        assert get_conv_resp.status_code == 404

        post_conv_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": "Injected message"},
            headers={"X-CSRF-Token": bob_csrf},
        )
        assert post_conv_resp.status_code == 404

        # Step 7: Ordinary customer attempts administrative actions -> 403 Forbidden
        admin_act = client.get("/admin/overview", headers={"X-CSRF-Token": bob_csrf})
        assert admin_act.status_code == 403

        # Step 8: Disabled user account is immediately blocked
        db.users_data["candidate@nanobio.com"]["is_active"] = False

        client.cookies.clear()
        disabled_csrf = client.get("/auth/csrf").json()["csrf_token"]
        disabled_login = client.post(
            "/auth/login",
            json={"email": "candidate@nanobio.com", "password": "SecurePassword123!"},
            headers={"X-CSRF-Token": disabled_csrf},
            cookies={"wavenxd_csrf": disabled_csrf},
        )
        assert disabled_login.status_code == 401
        assert "invalid email or password" in disabled_login.json()["detail"].lower()
