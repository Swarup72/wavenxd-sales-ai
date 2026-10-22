from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password, hash_token, verify_password
from app.domain.enums import InvitationStatus, UserRole
from app.main import app
from app.models.common import utc_now


class MockInvitationDB:
    def __init__(self):
        self.companies_data: dict[ObjectId, dict] = {}
        self.users_data: dict[str, dict] = {}
        self.invitations_data: dict[str, dict] = {}
        self.sessions_data: dict[str, dict] = {}
        self.command = AsyncMock(return_value={"ok": 1.0})


    @property
    def companies(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            comp = self.companies_data.get(cid)
            if comp and filter_dict.get("is_active", True) == comp.get("is_active", True):
                return comp
            return None

        col.find_one = AsyncMock(side_effect=find_one)
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

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
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

        col.insert_one = AsyncMock(side_effect=insert_one)
        col.find_one_and_update = AsyncMock(side_effect=find_one_and_update)
        col.update_one = AsyncMock(side_effect=update_one)
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
            if doc:
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        col.find_one = AsyncMock(side_effect=find_one)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        return col



@pytest.fixture
def invitation_context():
    db = MockInvitationDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    admin_id = ObjectId()
    company_id = ObjectId()

    db.companies_data[company_id] = {
        "_id": company_id,
        "name": "Stent Innovations Ltd",
        "is_active": True,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["admin@wavenxd.com"] = {
        "_id": admin_id,
        "email": "admin@wavenxd.com",
        "full_name": "WaveNxD Admin",
        "role": UserRole.ADMIN,
        "company_id": None,
        "password_hash": hash_password("ValidAdminPass123!"),
        "is_active": True,
        "must_change_password": False,
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
            "company_id": company_id,
        }


def test_admin_creates_invitation(invitation_context):
    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]

        # Log in as admin
        login_resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert login_resp.status_code == 200
        admin_csrf = login_resp.json()["csrf_token"]

        # Create customer invitation
        inv_resp = client.post(
            "/auth/invitations",
            json={
                "email": "newcustomer@stentinnovations.com",
                "company_id": str(invitation_context["company_id"]),
                "expiry_hours": 48,
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert inv_resp.status_code == 200
        data = inv_resp.json()
        assert data["email"] == "newcustomer@stentinnovations.com"
        assert data["company_id"] == str(invitation_context["company_id"])
        raw_token = data["invitation_token"]
        assert len(raw_token) >= 32

        # Verify only token hash is stored in DB
        db = invitation_context["db"]
        token_hash = hash_token(raw_token)
        assert token_hash in db.invitations_data
        stored_inv = db.invitations_data[token_hash]
        assert stored_inv["invitation_token_hash"] == token_hash
        assert raw_token not in str(stored_inv)


def test_customer_cannot_create_invitation(invitation_context):
    db = invitation_context["db"]
    customer_id = ObjectId()
    db.users_data["customer@stentinnovations.com"] = {
        "_id": customer_id,
        "email": "customer@stentinnovations.com",
        "full_name": "Customer User",
        "role": UserRole.CUSTOMER,
        "company_id": invitation_context["company_id"],
        "password_hash": hash_password("ValidCustomerPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]
        login_resp = client.post(
            "/auth/login",
            json={"email": "customer@stentinnovations.com", "password": "ValidCustomerPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert login_resp.status_code == 200
        customer_csrf = login_resp.json()["csrf_token"]

        # Attempt to create an invitation as customer -> 403 Forbidden
        inv_resp = client.post(
            "/auth/invitations",
            json={
                "email": "another@stentinnovations.com",
                "company_id": str(invitation_context["company_id"]),
            },
            headers={"X-CSRF-Token": customer_csrf},
        )
        assert inv_resp.status_code == 403
        assert "Administrator access required" in inv_resp.json()["detail"]


def test_invitation_acceptance_and_single_use(invitation_context):
    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]

        # Admin logs in & creates invitation
        login_resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        admin_csrf = login_resp.json()["csrf_token"]

        inv_resp = client.post(
            "/auth/invitations",
            json={
                "email": "invited@stentinnovations.com",
                "company_id": str(invitation_context["company_id"]),
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        raw_token = inv_resp.json()["invitation_token"]

        # Simulate new customer in anonymous browser (clear admin cookies)
        client.cookies.clear()

        # 1. Reject weak password
        fresh_csrf = client.get("/auth/csrf").json()["csrf_token"]

        weak_resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "short",
                "full_name": "Invited Customer",
            },
            headers={"X-CSRF-Token": fresh_csrf},
            cookies={"wavenxd_csrf": fresh_csrf},
        )
        assert weak_resp.status_code == 422 or weak_resp.status_code == 400

        # 2. Accept with strong password
        accept_resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "StrongCustomerPass123!",
                "full_name": "Invited Customer",
            },
            headers={"X-CSRF-Token": fresh_csrf},
            cookies={"wavenxd_csrf": fresh_csrf},
        )
        assert accept_resp.status_code == 200
        user_data = accept_resp.json()
        assert user_data["email"] == "invited@stentinnovations.com"
        assert user_data["role"] == "customer"
        assert user_data["company_id"] == str(invitation_context["company_id"])

        # 3. Single-use: attempting to accept again must fail
        reuse_resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "StrongCustomerPass123!",
            },
            headers={"X-CSRF-Token": fresh_csrf},
            cookies={"wavenxd_csrf": fresh_csrf},
        )
        assert reuse_resp.status_code == 404
        assert "already been used" in reuse_resp.json()["detail"].lower()


def test_expired_invitation_rejection(invitation_context):
    db = invitation_context["db"]
    raw_token = "expired-token-12345"
    token_hash = hash_token(raw_token)

    # Insert an invitation that expired 1 hour ago
    now = utc_now()
    db.invitations_data[token_hash] = {
        "_id": ObjectId(),
        "invitation_token_hash": token_hash,
        "email": "late@stentinnovations.com",
        "company_id": invitation_context["company_id"],
        "invited_by_user_id": invitation_context["admin_id"],
        "status": InvitationStatus.PENDING,
        "expires_at": now - timedelta(hours=1),
        "created_at": now - timedelta(hours=49),
        "updated_at": now - timedelta(hours=49),
    }

    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]
        resp = client.post(
            "/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "StrongCustomerPass123!",
            },
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert resp.status_code == 404
        assert "expired" in resp.json()["detail"].lower()
