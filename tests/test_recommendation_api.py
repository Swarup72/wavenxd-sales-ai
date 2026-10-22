from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.domain.enums import ProductMatchStatus, ProductStatus, UserRole
from app.main import app
from app.models.common import utc_now


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


class MockRecDB:
    def __init__(self):
        self.users_data: dict[str, dict] = {}
        self.sessions_data: dict[str, dict] = {}
        self.companies_data: dict[ObjectId, dict] = {}
        self.products_data: dict[ObjectId, dict] = {}
        self.assignments_data: dict[tuple[ObjectId, ObjectId], dict] = {}
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


@pytest.fixture
def rec_api_context():
    db = MockRecDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    admin_id = ObjectId()
    cust_a_id = ObjectId()
    cust_b_id = ObjectId()
    company_a_id = ObjectId()
    company_b_id = ObjectId()

    db.companies_data[company_a_id] = {
        "_id": company_a_id,
        "name": "Alpha Coatings Ltd",
        "is_active": True,
    }
    db.companies_data[company_b_id] = {
        "_id": company_b_id,
        "name": "Beta Labs Inc",
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

    db.users_data["user@alphacoatings.com"] = {
        "_id": cust_a_id,
        "email": "user@alphacoatings.com",
        "full_name": "Dr. Alice",
        "role": UserRole.CUSTOMER,
        "company_id": company_a_id,
        "password_hash": hash_password("ValidCustPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["user@betalabs.com"] = {
        "_id": cust_b_id,
        "email": "user@betalabs.com",
        "full_name": "Bob Builder",
        "role": UserRole.CUSTOMER,
        "company_id": company_b_id,
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
        "name": "Standard Ultrasonic Nozzle (Torch / Conical / Flat)",
        "catalog_key": "standard-nozzle-60khz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "torch / conical / flat",
        "feed_configuration": "standard",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Lab spray drying", "Spray pyrolysis"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
    }

    db.products_data[p_high_flow] = {
        "_id": p_high_flow,
        "name": "High-Flow Conical Ultrasonic Nozzle - 60 kHz",
        "catalog_key": "high-flow-conical-60khz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
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
    db.assignments_data[(company_a_id, p_std_60k)] = {
        "_id": ObjectId(),
        "company_id": company_a_id,
        "product_id": p_std_60k,
        "is_active": True,
    }
    db.assignments_data[(company_a_id, p_draft)] = {
        "_id": ObjectId(),
        "company_id": company_a_id,
        "product_id": p_draft,
        "is_active": True,
    }

    # Company B is assigned high-flow-conical-60khz
    db.assignments_data[(company_b_id, p_high_flow)] = {
        "_id": ObjectId(),
        "company_id": company_b_id,
        "product_id": p_high_flow,
        "is_active": True,
    }

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "db": db,
            "company_a_id": company_a_id,
            "company_b_id": company_b_id,
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


def test_customer_recommendation_auth_and_company_scoping(rec_api_context):
    with TestClient(app) as client:
        # 1. Unauthenticated request rejected with 401
        resp_unauth = client.post("/customer/recommendations", json={"application": "Lab spray drying"})
        assert resp_unauth.status_code == 401

        # 2. Customer A logs in
        auth_a = login_user(client, "user@alphacoatings.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        # Customer A evaluates "Lab spray drying":
        # Candidate pool for Customer A ONLY contains Company A's active, published, verified products
        # Draft product p_draft must NOT enter the candidate pool
        # Company B's high-flow nozzle must NOT enter Customer A's pool
        req_payload = {
            "application": "Lab spray drying",
            "flow_rate_ml_min": 2.0,
            "viscosity_cp": 10.0,
        }
        resp = client.post("/customer/recommendations", json=req_payload, headers=headers_a)
        assert resp.status_code == 200
        data = resp.json()

        assert data["overall_outcome"] == ProductMatchStatus.MATCH
        assert len(data["confirmed_recommendations"]) == 1
        assert data["confirmed_recommendations"][0]["catalog_key"] == "standard-nozzle-60khz"

        # Verify unauthorized products never reached the candidate evaluations
        eval_keys = [e["catalog_key"] for e in data["candidate_evaluations"]]
        assert "high-flow-conical-60khz" not in eval_keys
        assert "standard-nozzle-torch-180khz" not in eval_keys


def test_customer_without_entitlement_for_application(rec_api_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "user@alphacoatings.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        # Customer A needs "Industrial spray drying" (flow rate 100 ml/min)
        # But Customer A is ONLY assigned the standard 60 kHz nozzle (which maxes out at 5 ml/min)
        req_payload = {
            "application": "Industrial spray drying",
            "flow_rate_ml_min": 100.0,
            "viscosity_cp": 15.0,
        }
        resp = client.post("/customer/recommendations", json=req_payload, headers=headers_a)
        assert resp.status_code == 200
        data = resp.json()

        # Outcome is NO_MATCH because Company A does not hold the high-flow entitlement
        assert data["overall_outcome"] == ProductMatchStatus.NO_MATCH
        assert len(data["confirmed_recommendations"]) == 0


def test_customer_isolation_between_companies(rec_api_context):
    with TestClient(app) as client:
        # Customer B logs in (Company B is assigned high-flow-conical-60khz)
        auth_b = login_user(client, "user@betalabs.com")
        headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}

        req_payload = {
            "application": "Industrial spray drying",
            "flow_rate_ml_min": 100.0,
            "viscosity_cp": 15.0,
        }
        resp = client.post("/customer/recommendations", json=req_payload, headers=headers_b)
        assert resp.status_code == 200
        data = resp.json()

        # Company B has high-flow nozzle assigned, so it confirms match
        assert data["overall_outcome"] == ProductMatchStatus.MATCH
        assert len(data["confirmed_recommendations"]) == 1
        assert data["confirmed_recommendations"][0]["catalog_key"] == "high-flow-conical-60khz"

        # Customer B does NOT see Company A's standard nozzle
        eval_keys = [e["catalog_key"] for e in data["candidate_evaluations"]]
        assert "standard-nozzle-60khz" not in eval_keys


def test_admin_diagnostic_recommendation_endpoint(rec_api_context):
    with TestClient(app) as client:
        # 1. Customer denied from admin diagnostic endpoint
        login_user(client, "user@alphacoatings.com")
        resp_cust = client.post("/admin/recommendations/evaluate", json={"application": "Lab spray drying"})
        assert resp_cust.status_code == 403

    with TestClient(app) as client:
        # 2. Admin logs in
        auth_admin = login_user(client, "admin@wavenxd.com")
        headers = {"X-CSRF-Token": auth_admin["csrf_token"]}

        # Diagnostic across full catalog
        req = {"application": "Industrial spray drying", "flow_rate_ml_min": 100.0}
        resp = client.post("/admin/recommendations/evaluate", json=req, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_outcome"] == ProductMatchStatus.MATCH
        assert any(e["catalog_key"] == "high-flow-conical-60khz" for e in data["confirmed_recommendations"])

        # Diagnostic scoped to Company A via company_id query param
        cid = str(rec_api_context["company_a_id"])
        resp_cid = client.post(f"/admin/recommendations/evaluate?company_id={cid}", json=req, headers=headers)
        assert resp_cid.status_code == 200
        data_cid = resp_cid.json()
        # High flow is not assigned to Company A, so no confirmed match for Company A
        assert len(data_cid["confirmed_recommendations"]) == 0
