import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.domain.enums import ProductStatus
from app.main import app


def login_helper(client: TestClient, email: str, password: str):
    csrf_resp = client.get("/auth/csrf")
    assert csrf_resp.status_code == 200
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = client.post(
        "/auth/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_resp.status_code == 200
    new_csrf = login_resp.json().get("csrf_token", csrf_token)
    return login_resp, new_csrf


def test_admin_portal_page_served():
    """Verifies that /admin and /admin/ serve the admin.html single-page shell."""
    with TestClient(app) as client:
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "WaveNxD Admin Control Center" in resp.text
        assert "adminShell" in resp.text
        assert "accessDeniedView" in resp.text

        resp_slash = client.get("/admin/")
        assert resp_slash.status_code == 200
        assert "WaveNxD Admin Control Center" in resp_slash.text


def test_admin_routes_enforce_role_authorization():
    """
    Verifies that:
    1. Unauthenticated requests to /admin/* endpoints receive 401 Unauthorized.
    2. Customer sessions (Alice) receive 403 Forbidden on all /admin/* endpoints.
    3. Admin sessions receive 200 OK.
    """
    with TestClient(app) as client:
        # 1. Unauthenticated request
        unauth_resp = client.get("/admin/overview")
        assert unauth_resp.status_code == 401

        # 2. Customer login (Alice)
        alice_login, _ = login_helper(client, "alice@alphapharma.com", "ValidCustPass123!")
        assert alice_login.status_code == 200

        # Customer attempts to view overview -> 403
        cust_resp = client.get("/admin/overview")
        assert cust_resp.status_code == 403
        assert "Administrator access required" in cust_resp.text

        # Customer attempts to view audit logs -> 403
        audit_resp = client.get("/admin/audit-logs")
        assert audit_resp.status_code == 403

        # Customer attempts to access companies -> 403
        comp_resp = client.get("/admin/companies")
        assert comp_resp.status_code == 403

        # Logout customer
        client.post("/auth/logout")

        # 3. Admin login
        admin_login, _ = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")
        assert admin_login.status_code == 200

        admin_resp = client.get("/admin/overview")
        assert admin_resp.status_code == 200
        data = admin_resp.json()
        assert "total_companies" in data
        assert "total_users" in data
        assert "total_products" in data
        assert "active_assignments" in data


def test_admin_overview_metrics():
    """Verifies that /admin/overview returns verified counts from MongoDB."""
    with TestClient(app) as client:
        _, _ = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")
        resp = client.get("/admin/overview")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_companies"] >= 1
        assert data["total_users"] >= 2
        assert data["total_products"] >= 1
        assert data["primary_provider"] is not None


def test_admin_company_crud_and_audit():
    """Verifies creating, editing, and listing companies via admin endpoints with audit logging."""
    with TestClient(app) as client:
        _, admin_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        # 1. Create company
        new_comp_payload = {
            "name": f"Delta Biopharma Technologies {ObjectId()}",
            "contact_email": "rnd@deltabio.com",
            "notes": "Medical device micro-coating and atomization R&D",
        }
        create_resp = client.post(
            "/admin/companies",
            json=new_comp_payload,
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert create_resp.status_code == 200
        comp_data = create_resp.json()
        comp_id = comp_data["id"]

        # 2. Get company detail
        detail_resp = client.get(f"/admin/companies/{comp_id}")
        assert detail_resp.status_code == 200
        assert "Delta Biopharma" in detail_resp.json()["name"]

        # 3. Update company
        update_resp = client.patch(
            f"/admin/companies/{comp_id}",
            json={"contact_email": "operations@deltabio.com", "is_active": False},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["is_active"] is False
        assert update_resp.json()["contact_email"] == "operations@deltabio.com"

        # 4. Check audit log
        audit_resp = client.get("/admin/audit-logs?action=CREATE_COMPANY")
        assert audit_resp.status_code == 200
        audit_entries = audit_resp.json()
        assert any(e["target_id"] == comp_id for e in audit_entries)


def test_admin_user_management_and_lockout_protection():
    """Verifies listing users, updating user status, and last admin lockout protection."""
    with TestClient(app) as client:
        _, admin_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        # 1. List users
        users_resp = client.get("/admin/users")
        assert users_resp.status_code == 200
        users = users_resp.json()
        assert len(users) >= 2

        alice_entry = next(u for u in users if u["email"] == "alice@alphapharma.com")
        admin_entry = next(u for u in users if u["email"] == "admin@wavenxd.com")

        # 2. Update customer user name
        patch_user_resp = client.patch(
            f"/admin/users/{alice_entry['id']}",
            json={"full_name": "Dr. Alice Smith"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert patch_user_resp.status_code == 200
        assert patch_user_resp.json()["full_name"] == "Dr. Alice Smith"

        # 3. Protection: attempt to deactivate the last active administrator
        deactivate_admin_resp = client.patch(
            f"/admin/users/{admin_entry['id']}",
            json={"is_active": False},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert deactivate_admin_resp.status_code == 400
        assert "Cannot deactivate the last active administrator" in deactivate_admin_resp.json()["detail"]


def test_admin_user_password_reset():
    """Verifies that admin can safely reset a user password via Argon2id."""
    with TestClient(app) as client:
        _, admin_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        # Find Bob's ID
        users_resp = client.get("/admin/users")
        bob_entry = next(u for u in users_resp.json() if u["email"] == "bob@betacoatings.com")

        # Reset password with strong password
        new_pass = "BrandNewValidPass456!"
        reset_resp = client.post(
            f"/admin/users/{bob_entry['id']}/reset-password",
            json={"password": new_pass},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert reset_resp.status_code == 200
        assert "successfully reset" in reset_resp.json()["message"]

        # Verify Bob can now log in with the new password
        client.post("/auth/logout")
        bob_login, _ = login_helper(client, "bob@betacoatings.com", new_pass)
        assert bob_login.status_code == 200

        # Reset Bob's password back to default for other tests
        client.post("/auth/logout")
        _, admin_reset_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")
        client.post(
            f"/admin/users/{bob_entry['id']}/reset-password",
            json={"password": "ValidCustPass123!"},
            headers={"X-CSRF-Token": admin_reset_csrf},
        )


def test_admin_product_catalog_governance():
    """Verifies product creation, technical review flag management, and publishing."""
    with TestClient(app) as client:
        _, admin_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        unique_key = f"hypersonic-{ObjectId()}"
        new_prod_payload = {
            "name": "WaveNxD HyperSonic Test Nozzle",
            "catalog_key": unique_key,
            "category": "Ultra High Frequency",
            "frequency_khz": 180.0,
            "droplet_size_um": 12.0,
            "flow_rate_max_ml_min": 2.5,
            "viscosity_max_cp": 15.0,
            "applications": ["semiconductor thin films", "stent coating"],
            "status": "draft",
            "technical_review_required": True,
            "catalog_notes": "Awaiting final lab droplet measurement verification",
        }
        create_resp = client.post(
            "/admin/products",
            json=new_prod_payload,
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert create_resp.status_code == 200
        prod_data = create_resp.json()
        assert prod_data["name"] == "WaveNxD HyperSonic Test Nozzle"
        assert prod_data["technical_review_required"] is True
        prod_id = prod_data["id"]

        # 2. Check technical review queue
        review_resp = client.get("/admin/technical-review-queue")
        assert review_resp.status_code == 200
        queue_data = review_resp.json()
        assert any(p["id"] == prod_id for p in queue_data["flagged_products"])

        # 3. Approve technical review & publish product
        clear_resp = client.post(
            f"/admin/products/{prod_id}/clear-review",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert clear_resp.status_code == 200
        cleared_data = clear_resp.json()
        assert cleared_data["technical_review_required"] is False
        assert cleared_data["status"] == "published"


def test_admin_assignments_matrix():
    """Verifies granting, listing, and revoking product entitlements across companies."""
    with TestClient(app) as client:
        _, admin_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        # Get a company and product
        comp_resp = client.get("/admin/companies")
        prod_resp = client.get("/admin/products")
        comp_id = comp_resp.json()[0]["id"]
        # Find a published product
        pub_prod = next(p for p in prod_resp.json() if p["status"] == "published" and not p["technical_review_required"])
        prod_id = pub_prod["id"]

        # 1. List assignments
        assign_resp = client.get("/admin/assignments")
        assert assign_resp.status_code == 200
        assignments = assign_resp.json()
        assert isinstance(assignments, list)

        # 2. Assign product to company
        assign_call = client.post(
            f"/admin/companies/{comp_id}/products/{prod_id}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert assign_call.status_code == 200
        assert assign_call.json()["is_active"] is True

        # 3. Deactivate assignment
        deact_call = client.delete(
            f"/admin/companies/{comp_id}/products/{prod_id}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert deact_call.status_code == 200
        assert deact_call.json()["status"] == "ok"


def test_admin_provider_status_sanitized():
    """Verifies /admin/provider-status provides sanitized model info and zero secret leakage."""
    with TestClient(app) as client:
        _, _ = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")
        resp = client.get("/admin/provider-status")
        assert resp.status_code == 200
        data = resp.json()

        assert "primary_llm" in data
        assert "primary_model" in data
        assert "stt_model" in data
        assert "tts_model" in data
        assert "budget_mode" in data

        # CRITICAL SECURITY: Verify zero API keys or secrets in response text
        raw_text = resp.text.lower()
        assert "api_key" not in raw_text
        assert "gsk_" not in raw_text
        assert "aizasy" not in raw_text


def test_admin_support_conversations_endpoint():
    """Verifies listing and inspecting customer consultations for technical support."""
    with TestClient(app) as client:
        # Create a conversation as Alice first
        _, alice_csrf = login_helper(client, "alice@alphapharma.com", "ValidCustPass123!")
        create_conv_resp = client.post(
            "/customer/conversations",
            json={"title": "Ultrasonic Lab Coater Consultation"},
            headers={"X-CSRF-Token": alice_csrf},
        )
        assert create_conv_resp.status_code == 201
        conv_id = create_conv_resp.json()["id"]

        # View as Admin
        client.post("/auth/logout")
        _, admin_support_csrf = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")
        support_resp = client.get("/admin/support/conversations")
        assert support_resp.status_code == 200
        convs = support_resp.json()
        assert any(c["id"] == conv_id for c in convs)

        # Inspect details
        inspect_resp = client.get(f"/admin/support/conversations/{conv_id}")
        assert inspect_resp.status_code == 200
        detail = inspect_resp.json()
        assert detail["title"] == "Ultrasonic Lab Coater Consultation"
        assert detail["company_name"] is not None


def test_admin_csrf_protection_on_mutations():
    """Verifies that state-changing admin endpoints reject requests without a valid CSRF token."""
    with TestClient(app) as client:
        _, _ = login_helper(client, "admin@wavenxd.com", "ValidAdminPass123!")

        # POST without X-CSRF-Token -> 403 Forbidden
        bad_post = client.post(
            "/admin/companies",
            json={"name": "Attacker Company Corp"},
        )
        assert bad_post.status_code == 403
        assert "CSRF" in bad_post.text
