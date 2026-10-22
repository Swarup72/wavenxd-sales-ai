from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.domain.enums import AccessRequestStatus, ProductStatus, UserRole
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


class MockCustomerDB:
    def __init__(self):
        self.users_data: dict[str, dict] = {}
        self.sessions_data: dict[str, dict] = {}
        self.companies_data: dict[ObjectId, dict] = {}
        self.products_data: dict[ObjectId, dict] = {}
        self.assignments_data: dict[tuple[ObjectId, ObjectId], dict] = {}
        self.access_requests_data: dict[ObjectId, dict] = {}
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
            comp = self.companies_data.get(cid)
            if not comp:
                return None
            if "is_active" in filter_dict and comp.get("is_active") != filter_dict["is_active"]:
                return None
            return comp

        col.find_one = AsyncMock(side_effect=find_one)
        return col

    @property
    def products(self):
        col = MagicMock()

        async def find_one(filter_dict):
            pid = filter_dict.get("_id")
            prod = self.products_data.get(pid)
            if not prod:
                return None
            if "status" in filter_dict and prod.get("status") != filter_dict["status"]:
                return None
            if filter_dict.get("technical_review_required") is False and prod.get("technical_review_required", False):
                return None
            return prod

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

        async def find_one(filter_dict):
            cid = filter_dict.get("company_id")
            pid = filter_dict.get("product_id")
            assign = self.assignments_data.get((cid, pid))
            if not assign:
                return None
            if "is_active" in filter_dict and assign.get("is_active") != filter_dict["is_active"]:
                return None
            return assign

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

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        return col

    @property
    def access_requests(self):
        col = MagicMock()

        async def find_one(filter_dict):
            for req in self.access_requests_data.values():
                match = True
                for k, v in filter_dict.items():
                    if req.get(k) != v:
                        match = False
                        break
                if match:
                    return req
            return None

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for req in self.access_requests_data.values():
                match = True
                for k, v in filter_dict.items():
                    if req.get(k) != v:
                        match = False
                        break
                if match:
                    items.append(req)
            return MockCursor(items)

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.access_requests_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.insert_one = AsyncMock(side_effect=insert_one)
        return col


@pytest.fixture
def customer_api_context():
    db = MockCustomerDB()
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
        "name": "Alpha Pharma Ltd",
        "is_active": True,
    }
    db.companies_data[company_b_id] = {
        "_id": company_b_id,
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

    db.users_data["user@alphapharma.com"] = {
        "_id": cust_a_id,
        "email": "user@alphapharma.com",
        "full_name": "Dr. Alice",
        "role": UserRole.CUSTOMER,
        "company_id": company_a_id,
        "password_hash": hash_password("ValidCustPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["user@betacoatings.com"] = {
        "_id": cust_b_id,
        "email": "user@betacoatings.com",
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
    p_published_1 = ObjectId()
    p_published_2 = ObjectId()
    p_draft = ObjectId()

    db.products_data[p_published_1] = {
        "_id": p_published_1,
        "name": "Standard Ultrasonic Nozzle 60kHz",
        "catalog_key": "standard-nozzle-60khz",
        "category": "Ultrasonic Nozzles",
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "applications": ["Precision Coating"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.products_data[p_published_2] = {
        "_id": p_published_2,
        "name": "Wide-Spray Ultrasonic Nozzle 120kHz",
        "catalog_key": "wide-spray-120khz",
        "category": "Ultrasonic Nozzles",
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "applications": ["Solar Cell Coating"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.products_data[p_draft] = {
        "_id": p_draft,
        "name": "180kHz Stent Coating Nozzle",
        "catalog_key": "stent-nozzle-180khz",
        "category": "Specialized Nozzles",
        "status": ProductStatus.DRAFT,
        "technical_review_required": True,
        "applications": ["Stents"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    # Company A is assigned p_published_1
    db.assignments_data[(company_a_id, p_published_1)] = {
        "_id": ObjectId(),
        "company_id": company_a_id,
        "product_id": p_published_1,
        "is_active": True,
        "assigned_by_user_id": admin_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    # Company B is assigned p_published_2
    db.assignments_data[(company_b_id, p_published_2)] = {
        "_id": ObjectId(),
        "company_id": company_b_id,
        "product_id": p_published_2,
        "is_active": True,
        "assigned_by_user_id": admin_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "db": db,
            "company_a_id": company_a_id,
            "company_b_id": company_b_id,
            "cust_a_id": cust_a_id,
            "cust_b_id": cust_b_id,
            "product_published_1": p_published_1,
            "product_published_2": p_published_2,
            "product_draft": p_draft,
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


def test_customer_routes_require_customer_authentication(customer_api_context):
    with TestClient(app) as client:
        # 1. Unauthenticated requests are rejected with 401
        assert client.get("/customer/products").status_code == 401
        assert client.get("/customer/access-requests").status_code == 401

        # 2. Admin attempting customer routes is rejected with 403
        login_user(client, "admin@wavenxd.com")
        assert client.get("/customer/products").status_code == 403
        assert client.get("/customer/access-requests").status_code == 403


def test_customer_assigned_products_and_isolation(customer_api_context):
    with TestClient(app) as client:
        # Customer A logs in
        login_user(client, "user@alphapharma.com")

        resp = client.get("/customer/products")
        assert resp.status_code == 200
        products = resp.json()

        # Customer A only sees product_published_1
        assert len(products) == 1
        assert products[0]["id"] == str(customer_api_context["product_published_1"])
        assert products[0]["name"] == "Standard Ultrasonic Nozzle 60kHz"

        # Customer A does NOT see product_published_2 (assigned to Company B) or product_draft
        ids = [p["id"] for p in products]
        assert str(customer_api_context["product_published_2"]) not in ids
        assert str(customer_api_context["product_draft"]) not in ids

    # Now Customer B logs in on separate client
    with TestClient(app) as client_b:
        login_user(client_b, "user@betacoatings.com")

        resp_b = client_b.get("/customer/products")
        assert resp_b.status_code == 200
        products_b = resp_b.json()

        # Customer B only sees product_published_2
        assert len(products_b) == 1
        assert products_b[0]["id"] == str(customer_api_context["product_published_2"])
        assert products_b[0]["name"] == "Wide-Spray Ultrasonic Nozzle 120kHz"


def test_submit_customer_access_request_workflow(customer_api_context):
    with TestClient(app) as client:
        auth_info = login_user(client, "user@alphapharma.com")
        headers = {"X-CSRF-Token": auth_info["csrf_token"]}

        target_pid = str(customer_api_context["product_published_2"])
        already_assigned_pid = str(customer_api_context["product_published_1"])
        draft_pid = str(customer_api_context["product_draft"])
        nonexistent_pid = str(ObjectId())

        # 1. Non-existent product returns generic 404
        resp = client.post(
            "/customer/access-requests",
            json={"product_id": nonexistent_pid, "reason": "Test"},
            headers=headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Product not found"

        # 2. Draft/unverified product returns generic 404 without leaking existence
        resp_draft = client.post(
            "/customer/access-requests",
            json={"product_id": draft_pid, "reason": "Interested in stents"},
            headers=headers,
        )
        assert resp_draft.status_code == 404
        assert resp_draft.json()["detail"] == "Product not found"

        # 3. Already assigned product returns 400
        resp_assigned = client.post(
            "/customer/access-requests",
            json={"product_id": already_assigned_pid, "reason": "Duplicate"},
            headers=headers,
        )
        assert resp_assigned.status_code == 400
        assert "already assigned" in resp_assigned.json()["detail"]

        # 4. Valid submission returns 201 Created
        resp_valid = client.post(
            "/customer/access-requests",
            json={"product_id": target_pid, "reason": "Interested in solar trial"},
            headers=headers,
        )
        assert resp_valid.status_code == 201
        data = resp_valid.json()
        assert data["product_id"] == target_pid
        assert data["status"] == "pending"
        assert data["reason"] == "Interested in solar trial"

        # 5. Duplicate request while pending is rejected with 400
        resp_dup = client.post(
            "/customer/access-requests",
            json={"product_id": target_pid},
            headers=headers,
        )
        assert resp_dup.status_code == 400
        assert "already pending" in resp_dup.json()["detail"]


def test_customer_access_requests_isolation(customer_api_context):
    db = customer_api_context["db"]
    now = utc_now()

    # Pre-populate requests for Company A and Company B
    req_a = ObjectId()
    req_b = ObjectId()

    db.access_requests_data[req_a] = {
        "_id": req_a,
        "company_id": customer_api_context["company_a_id"],
        "requested_by_user_id": customer_api_context["cust_a_id"],
        "product_id": customer_api_context["product_published_2"],
        "reason": "Alpha request",
        "status": AccessRequestStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }

    db.access_requests_data[req_b] = {
        "_id": req_b,
        "company_id": customer_api_context["company_b_id"],
        "requested_by_user_id": customer_api_context["cust_b_id"],
        "product_id": customer_api_context["product_published_1"],
        "reason": "Beta request",
        "status": AccessRequestStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }

    with TestClient(app) as client:
        # Customer A logs in
        login_user(client, "user@alphapharma.com")

        resp = client.get("/customer/access-requests")
        assert resp.status_code == 200
        reqs = resp.json()

        # Customer A can only see Company A's access requests
        assert len(reqs) == 1
        assert reqs[0]["id"] == str(req_a)
        assert reqs[0]["reason"] == "Alpha request"
