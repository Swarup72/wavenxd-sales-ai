from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import hash_password, hash_token
from app.domain.enums import UserRole
from app.main import app
from app.models.common import utc_now
from app.models.session import Session
from app.models.user import User


class MockAuthDB:
    def __init__(self):
        self.users_data: dict[str, dict] = {}
        self.sessions_data: dict[str, dict] = {}
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


@pytest.fixture
def auth_test_context():
    db = MockAuthDB()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = db
    mock_client.close = AsyncMock()

    # Pre-populate active admin and customer
    admin_id = ObjectId()
    customer_id = ObjectId()
    company_id = ObjectId()

    db.users_data["admin@wavenxd.com"] = {
        "_id": admin_id,
        "email": "admin@wavenxd.com",
        "full_name": "Admin User",
        "role": UserRole.ADMIN,
        "company_id": None,
        "password_hash": hash_password("ValidAdminPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["customer@client.com"] = {
        "_id": customer_id,
        "email": "customer@client.com",
        "full_name": "Customer User",
        "role": UserRole.CUSTOMER,
        "company_id": company_id,
        "password_hash": hash_password("ValidCustomerPass123!"),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["inactive@client.com"] = {
        "_id": ObjectId(),
        "email": "inactive@client.com",
        "full_name": "Inactive User",
        "role": UserRole.CUSTOMER,
        "company_id": company_id,
        "password_hash": hash_password("ValidPass123!"),
        "is_active": False,
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
            "customer_id": customer_id,
            "company_id": company_id,
        }


def test_csrf_rejection_and_acceptance(auth_test_context):
    with TestClient(app) as client:
        # 1. State-changing request without CSRF token is rejected with 403
        resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
        )
        assert resp.status_code == 403
        assert "CSRF token missing" in resp.json()["detail"]

        # 2. State-changing request with invalid CSRF token is rejected with 403
        resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": "bad-token"},
            cookies={"wavenxd_csrf": "different-token"},
        )
        assert resp.status_code == 403
        assert "Invalid CSRF token" in resp.json()["detail"]

        # 3. Requesting CSRF endpoint issues a valid CSRF token and cookie
        csrf_resp = client.get("/auth/csrf")
        assert csrf_resp.status_code == 200
        csrf_token = csrf_resp.json()["csrf_token"]
        assert len(csrf_token) >= 32

        # 4. State-changing request with matching CSRF cookie and header is accepted
        login_resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["user"]["email"] == "admin@wavenxd.com"


def test_login_success_and_cookie_attributes(auth_test_context):
    with TestClient(app) as client:
        csrf_resp = client.get("/auth/csrf")
        csrf_token = csrf_resp.json()["csrf_token"]

        resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Sensitive fields are NEVER returned in response
        assert "password_hash" not in data["user"]
        assert "session_token_hash" not in data

        # Safe user fields returned
        assert data["user"]["email"] == "admin@wavenxd.com"
        assert data["user"]["role"] == "admin"
        assert "csrf_token" in data

        # Check session cookie attributes
        cookies = resp.cookies
        assert "wavenxd_session" in cookies
        raw_cookie = resp.headers.get("set-cookie")
        assert "httponly" in raw_cookie.lower()
        assert "samesite=lax" in raw_cookie.lower()



def test_login_failure_cases_and_generic_errors(auth_test_context):
    with TestClient(app) as client:
        csrf_resp = client.get("/auth/csrf")
        csrf_token = csrf_resp.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf_token}
        cookies = {"wavenxd_csrf": csrf_token}

        # 1. Non-existent email
        resp = client.post(
            "/auth/login",
            json={"email": "nonexistent@wavenxd.com", "password": "SomePassword123!"},
            headers=headers,
            cookies=cookies,
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"

        # 2. Wrong password
        resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "WrongPassword123!"},
            headers=headers,
            cookies=cookies,
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"

        # 3. Inactive user
        resp = client.post(
            "/auth/login",
            json={"email": "inactive@client.com", "password": "ValidPass123!"},
            headers=headers,
            cookies=cookies,
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"


def test_current_user_me_endpoint_and_revocation(auth_test_context):
    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]

        # Log in as customer
        login_resp = client.post(
            "/auth/login",
            json={"email": "customer@client.com", "password": "ValidCustomerPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert login_resp.status_code == 200
        customer_csrf = login_resp.json()["csrf_token"]

        # Fetch /auth/me with session cookie
        me_resp = client.get("/auth/me")
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "customer@client.com"
        assert me_data["role"] == "customer"
        assert me_data["company_id"] == str(auth_test_context["company_id"])

        # Logout with CSRF token
        logout_resp = client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": customer_csrf},
        )
        assert logout_resp.status_code == 200

        # After logout, /auth/me returns 401
        me_after_resp = client.get("/auth/me")
        assert me_after_resp.status_code == 401


def test_cookie_secure_attribute_in_production(auth_test_context, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    # Clear settings cache so new env is loaded
    get_settings.cache_clear()

    with TestClient(app) as client:
        csrf_token = client.get("/auth/csrf").json()["csrf_token"]
        login_resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_token},
            cookies={"wavenxd_csrf": csrf_token},
        )
        assert login_resp.status_code == 200
        raw_cookie = login_resp.headers.get("set-cookie")
        assert "Secure" in raw_cookie

    get_settings.cache_clear()


def test_no_public_registration_and_no_unauthenticated_admin_creation():
    with TestClient(app) as client:
        # Public self-registration should not exist
        resp1 = client.post("/auth/register", json={"email": "test@test.com"})
        assert resp1.status_code in (404, 405)

        resp2 = client.post("/api/register", json={"email": "test@test.com"})
        assert resp2.status_code in (404, 405)

        # Unauthenticated admin creation should not exist
        resp3 = client.post("/admin/create", json={"email": "admin2@test.com"})
        assert resp3.status_code in (404, 405)


def test_csrf_regression_login_with_existing_session_and_token_refresh(auth_test_context):
    """
    Regression test verifying:
    1. Valid CSRF login with double-submit cookie.
    2. Re-login / user-switching when an existing session cookie is present.
    3. Token refresh via GET /auth/csrf while authenticated preserves session synchronization.
    4. Missing token, mismatched token, and missing CSRF cookie are strictly rejected.
    """
    with TestClient(app) as client:
        # Case A: Missing token header -> 403 CSRF token missing
        resp_missing = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
        )
        assert resp_missing.status_code == 403
        assert "CSRF token missing" in resp_missing.json()["detail"]

        # Case B: Missing CSRF cookie -> 403 Invalid CSRF token
        resp_no_cookie = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": "some-random-token"},
        )
        assert resp_no_cookie.status_code == 403
        assert "Invalid CSRF token" in resp_no_cookie.json()["detail"]

        # Case C: Mismatched CSRF token header vs cookie -> 403 Invalid CSRF token
        resp_mismatch = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": "token-a"},
            cookies={"wavenxd_csrf": "token-b"},
        )
        assert resp_mismatch.status_code == 403
        assert "Invalid CSRF token" in resp_mismatch.json()["detail"]

        # Case D: Valid CSRF login
        csrf_init = client.get("/auth/csrf").json()["csrf_token"]
        login_a = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "ValidAdminPass123!"},
            headers={"X-CSRF-Token": csrf_init},
        )
        assert login_a.status_code == 200
        admin_session_csrf = login_a.json()["csrf_token"]

        # Case E: Token refresh via GET /auth/csrf while session is active
        # Must return the session's CSRF token, keeping session synchronized
        refresh_resp = client.get("/auth/csrf")
        assert refresh_resp.status_code == 200
        refreshed_csrf = refresh_resp.json()["csrf_token"]
        assert refreshed_csrf == admin_session_csrf

        # Authenticated GET request must succeed
        me_resp = client.get("/auth/me")
        assert me_resp.status_code == 200

        # Case F: Re-login / user-switching with pre-existing session cookie present
        # Obtains new CSRF token for login page and logs in as customer
        login_csrf = client.get("/auth/csrf").json()["csrf_token"]
        login_b = client.post(
            "/auth/login",
            json={"email": "customer@client.com", "password": "ValidCustomerPass123!"},
            headers={"X-CSRF-Token": login_csrf},
        )
        assert login_b.status_code == 200
        assert login_b.json()["user"]["email"] == "customer@client.com"
        assert login_b.json()["user"]["role"] == "customer"


def test_demo_personas_login_success(auth_test_context):
    """
    Verifies that all three fast-access demo personas from the login interface
    (Admin, Alice, Bob) authenticate successfully using their configured passwords.
    """
    db = auth_test_context["db"]
    alpha_cid = ObjectId()
    beta_cid = ObjectId()

    from app.services.demo_seed import (
        DEFAULT_DEMO_ADMIN_PASSWORD,
        DEFAULT_DEMO_CUSTOMER_PASSWORD,
    )

    db.users_data["alice@alphapharma.com"] = {
        "_id": ObjectId(),
        "email": "alice@alphapharma.com",
        "full_name": "Dr. Alice",
        "role": UserRole.CUSTOMER,
        "company_id": alpha_cid,
        "password_hash": hash_password(DEFAULT_DEMO_CUSTOMER_PASSWORD),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    db.users_data["bob@betacoatings.com"] = {
        "_id": ObjectId(),
        "email": "bob@betacoatings.com",
        "full_name": "Bob Builder",
        "role": UserRole.CUSTOMER,
        "company_id": beta_cid,
        "password_hash": hash_password(DEFAULT_DEMO_CUSTOMER_PASSWORD),
        "is_active": True,
        "must_change_password": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    with TestClient(app) as client:
        # 1. Admin persona login
        csrf = client.get("/auth/csrf").json()["csrf_token"]
        res_admin = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": DEFAULT_DEMO_ADMIN_PASSWORD},
            headers={"X-CSRF-Token": csrf},
        )
        assert res_admin.status_code == 200
        assert res_admin.json()["user"]["role"] == "admin"
        assert res_admin.json()["user"]["email"] == "admin@wavenxd.com"

        # 2. Alice persona login
        csrf = client.get("/auth/csrf").json()["csrf_token"]
        res_alice = client.post(
            "/auth/login",
            json={"email": "alice@alphapharma.com", "password": DEFAULT_DEMO_CUSTOMER_PASSWORD},
            headers={"X-CSRF-Token": csrf},
        )
        assert res_alice.status_code == 200
        assert res_alice.json()["user"]["role"] == "customer"
        assert res_alice.json()["user"]["company_id"] == str(alpha_cid)

        # 3. Bob persona login
        csrf = client.get("/auth/csrf").json()["csrf_token"]
        res_bob = client.post(
            "/auth/login",
            json={"email": "bob@betacoatings.com", "password": DEFAULT_DEMO_CUSTOMER_PASSWORD},
            headers={"X-CSRF-Token": csrf},
        )
        assert res_bob.status_code == 200
        assert res_bob.json()["user"]["role"] == "customer"
        assert res_bob.json()["user"]["company_id"] == str(beta_cid)


def test_login_missing_user_and_invalid_passwords_behavior(auth_test_context):
    """
    Confirms that missing users and wrong passwords both return 401 Unauthorized
    with the exact same generic error message to prevent user enumeration.
    """
    with TestClient(app) as client:
        csrf = client.get("/auth/csrf").json()["csrf_token"]

        # 1. Completely missing user
        missing_resp = client.post(
            "/auth/login",
            json={"email": "ghost.user@unknown.com", "password": "AnyValidPassword123!"},
            headers={"X-CSRF-Token": csrf},
        )
        assert missing_resp.status_code == 401
        assert missing_resp.json()["detail"] == "Invalid email or password"

        # 2. Existing user, wrong password
        wrong_resp = client.post(
            "/auth/login",
            json={"email": "admin@wavenxd.com", "password": "TotallyWrongPassword123!"},
            headers={"X-CSRF-Token": csrf},
        )
        assert wrong_resp.status_code == 401
        assert wrong_resp.json()["detail"] == "Invalid email or password"

        # 3. Empty password or malformed input
        bad_format_resp = client.post(
            "/auth/login",
            json={"email": "not-an-email", "password": "ValidPassword123!"},
            headers={"X-CSRF-Token": csrf},
        )
        assert bad_format_resp.status_code == 422



