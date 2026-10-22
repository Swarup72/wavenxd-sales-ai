from datetime import timedelta
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


class MockAdminDB:
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

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for c in self.companies_data.values():
                if "is_active" in filter_dict and c.get("is_active") != filter_dict["is_active"]:
                    continue
                items.append(c)
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
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

        async def update_one(filter_dict, update_dict, upsert=False):
            cid = filter_dict.get("company_id")
            pid = filter_dict.get("product_id")
            key = (cid, pid)
            if key not in self.assignments_data and upsert:
                self.assignments_data[key] = {
                    "_id": ObjectId(),
                    "company_id": cid,
                    "product_id": pid,
                    "is_active": True,
                    "assigned_by_user_id": ObjectId(),
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            assign = self.assignments_data.get(key)
            if assign:
                if "is_active" in filter_dict and assign.get("is_active") != filter_dict["is_active"]:
                    return MagicMock(modified_count=0)
                for k, v in update_dict.get("$set", {}).items():
                    assign[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.update_one = AsyncMock(side_effect=update_one)
        return col

    @property
    def access_requests(self):
        col = MagicMock()

        async def find_one(filter_dict):
            rid = filter_dict.get("_id")
            if rid:
                req = self.access_requests_data.get(rid)
                if req:
                    if "status" in filter_dict and req.get("status") != filter_dict["status"]:
                        return None
                    return req
                return None
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

        async def update_one(filter_dict, update_dict):
            rid = filter_dict.get("_id")
            req = self.access_requests_data.get(rid)
            if req:
                for k, v in update_dict.get("$set", {}).items():
                    req[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def find_one_and_update(filter_dict, update_dict, return_document=None):
            rid = filter_dict.get("_id")
            req = self.access_requests_data.get(rid)
            if not req:
                return None
            if "status" in filter_dict and req.get("status") != filter_dict["status"]:
                return None
            for k, v in update_dict.get("$set", {}).items():
                req[k] = v
            return req

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find_one_and_update = AsyncMock(side_effect=find_one_and_update)
        return col


@pytest.fixture
def admin_api_context():
    db = MockAdminDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    admin_id = ObjectId()
    customer_id = ObjectId()
    company_id = ObjectId()

    db.companies_data[company_id] = {
        "_id": company_id,
        "name": "Acme MedTech Corp",
        "is_active": True,
        "contact_email": "ops@acmemed.com",
        "notes": "Medical devices tier 1",
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

    db.users_data["customer@acmemed.com"] = {
        "_id": customer_id,
        "email": "customer@acmemed.com",
        "full_name": "Customer Engineer",
        "role": UserRole.CUSTOMER,
        "company_id": company_id,
        "password_hash": hash_password("ValidCustPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    # Catalog Products
    p_published = ObjectId()
    p_draft = ObjectId()
    db.products_data[p_published] = {
        "_id": p_published,
        "name": "Standard Ultrasonic Nozzle 60kHz",
        "catalog_key": "standard-nozzle-60khz",
        "category": "Ultrasonic Nozzles",
        "spray_pattern": "narrow",
        "frequency_khz": 60.0,
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "applications": ["Precision Coating"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.products_data[p_draft] = {
        "_id": p_draft,
        "name": "180kHz Stent Coating Nozzle",
        "catalog_key": "stent-nozzle-180khz",
        "category": "Specialized Nozzles",
        "frequency_khz": 180.0,
        "status": ProductStatus.DRAFT,
        "technical_review_required": True,
        "applications": ["Coronary Stent Coating"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "db": db,
            "admin_id": admin_id,
            "customer_id": customer_id,
            "company_id": company_id,
            "product_published": p_published,
            "product_draft": p_draft,
        }


def login_admin(client: TestClient) -> dict:
    csrf_resp = client.get("/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = client.post(
        "/auth/login",
        json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_resp.status_code == 200
    return {"csrf_token": login_resp.json()["csrf_token"]}


def login_customer(client: TestClient) -> dict:
    csrf_resp = client.get("/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = client.post(
        "/auth/login",
        json={"email": "customer@acmemed.com", "password": "ValidCustPass123!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_resp.status_code == 200
    return {"csrf_token": login_resp.json()["csrf_token"]}


def test_admin_routes_require_admin_authentication(admin_api_context):
    with TestClient(app) as client:
        # 1. Unauthenticated requests are rejected with 401
        assert client.get("/admin/companies").status_code == 401
        assert client.get("/admin/products").status_code == 401
        assert client.get(f"/admin/companies/{admin_api_context['company_id']}/products").status_code == 401
        assert client.get("/admin/access-requests").status_code == 401

        # 2. Customer user attempting administrative routes is rejected with 403
        login_customer(client)
        assert client.get("/admin/companies").status_code == 403
        assert client.get("/admin/products").status_code == 403
        assert client.get(f"/admin/companies/{admin_api_context['company_id']}/products").status_code == 403
        assert client.get("/admin/access-requests").status_code == 403


def test_list_companies_and_products(admin_api_context):
    with TestClient(app) as client:
        login_admin(client)

        # List companies
        resp = client.get("/admin/companies")
        assert resp.status_code == 200
        companies = resp.json()
        assert len(companies) == 1
        assert companies[0]["id"] == str(admin_api_context["company_id"])
        assert companies[0]["name"] == "Acme MedTech Corp"
        assert companies[0]["is_active"] is True

        # List products (returns all catalog products with status and review flags)
        resp = client.get("/admin/products")
        assert resp.status_code == 200
        products = resp.json()
        assert len(products) == 2
        p_names = {p["name"] for p in products}
        assert "Standard Ultrasonic Nozzle 60kHz" in p_names
        assert "180kHz Stent Coating Nozzle" in p_names


def test_assign_and_remove_company_product(admin_api_context):
    with TestClient(app) as client:
        auth_info = login_admin(client)
        headers = {"X-CSRF-Token": auth_info["csrf_token"]}

        cid = str(admin_api_context["company_id"])
        pid = str(admin_api_context["product_published"])
        draft_pid = str(admin_api_context["product_draft"])

        # 1. Cannot assign draft/unreviewed product
        resp = client.post(
            f"/admin/companies/{cid}/products/{draft_pid}",
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Only published products" in resp.json()["detail"]

        # 2. Assign published product
        resp = client.post(
            f"/admin/companies/{cid}/products/{pid}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_id"] == cid
        assert data["product_id"] == pid
        assert data["is_active"] is True

        # 3. View assigned products for company
        resp = client.get(f"/admin/companies/{cid}/products")
        assert resp.status_code == 200
        assigned_list = resp.json()
        assert len(assigned_list) == 1
        assert assigned_list[0]["product"]["id"] == pid
        assert assigned_list[0]["is_active"] is True

        # 4. Deactivate assignment
        del_resp = client.delete(
            f"/admin/companies/{cid}/products/{pid}",
            headers=headers,
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "ok"

        # 5. Deactivating again raises 404
        del_again = client.delete(
            f"/admin/companies/{cid}/products/{pid}",
            headers=headers,
        )
        assert del_again.status_code == 404


def test_access_request_approval_and_rejection(admin_api_context):
    db = admin_api_context["db"]
    cid = admin_api_context["company_id"]
    cust_id = admin_api_context["customer_id"]
    pid = admin_api_context["product_published"]

    # Pre-populate two access requests
    req1_id = ObjectId()
    req2_id = ObjectId()
    now = utc_now()

    db.access_requests_data[req1_id] = {
        "_id": req1_id,
        "company_id": cid,
        "requested_by_user_id": cust_id,
        "product_id": pid,
        "reason": "Requesting 60kHz nozzle for testing",
        "status": AccessRequestStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }

    db.access_requests_data[req2_id] = {
        "_id": req2_id,
        "company_id": cid,
        "requested_by_user_id": cust_id,
        "product_id": pid,
        "reason": "Requesting duplicate nozzle test",
        "status": AccessRequestStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }

    with TestClient(app) as client:
        auth_info = login_admin(client)
        headers = {"X-CSRF-Token": auth_info["csrf_token"]}

        # 1. List pending requests
        list_resp = client.get("/admin/access-requests?status=pending")
        assert list_resp.status_code == 200
        requests = list_resp.json()
        assert len(requests) == 2

        # 2. View individual request
        single_resp = client.get(f"/admin/access-requests/{req1_id}")
        assert single_resp.status_code == 200
        assert single_resp.json()["id"] == str(req1_id)
        assert single_resp.json()["status"] == "pending"

        # 3. Approve req1
        approve_resp = client.post(
            f"/admin/access-requests/{req1_id}/approve",
            json={"review_note": "Approved for 60-day pilot"},
            headers=headers,
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["company_id"] == str(cid)
        assert approve_resp.json()["product_id"] == str(pid)
        assert approve_resp.json()["is_active"] is True

        # Assignment is active in database
        assert db.assignments_data[(cid, pid)]["is_active"] is True

        # Attempting to re-approve already approved request fails with 400
        re_approve = client.post(
            f"/admin/access-requests/{req1_id}/approve",
            json={"review_note": "Duplicate approval"},
            headers=headers,
        )
        assert re_approve.status_code == 400
        assert "already been reviewed" in re_approve.json()["detail"]

        # 4. Reject req2
        reject_resp = client.post(
            f"/admin/access-requests/{req2_id}/reject",
            json={"review_note": "Duplicate request rejected"},
            headers=headers,
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"
        assert reject_resp.json()["review_note"] == "Duplicate request rejected"

        # Attempting to re-reject already reviewed request fails with 400
        re_reject = client.post(
            f"/admin/access-requests/{req2_id}/reject",
            headers=headers,
        )
        assert re_reject.status_code == 400
        assert "already been reviewed" in re_reject.json()["detail"]


def test_malformed_object_ids_in_admin_routes(admin_api_context):
    with TestClient(app) as client:
        auth_info = login_admin(client)
        headers = {"X-CSRF-Token": auth_info["csrf_token"]}

        bad_id = "invalid-oid-xyz"

        # Malformed company ID
        assert client.get(f"/admin/companies/{bad_id}/products").status_code == 400

        # Malformed product ID in assignment
        cid = str(admin_api_context["company_id"])
        resp = client.post(
            f"/admin/companies/{cid}/products/{bad_id}",
            headers=headers,
        )
        assert resp.status_code == 400

        # Malformed request ID
        assert client.get(f"/admin/access-requests/{bad_id}").status_code == 400
        assert client.post(
            f"/admin/access-requests/{bad_id}/approve",
            headers=headers,
        ).status_code == 400
