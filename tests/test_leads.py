from fastapi.testclient import TestClient

from app.domain.enums import LeadStage
from app.main import app
from tests.test_conversations import conversation_context, login_user


def test_customer_lead_creation_and_retrieval(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        # 1. Create a consultation
        conv_resp = client.post(
            "/customer/conversations",
            json={"title": "Stent Coating Project"},
            headers=headers_a,
        )
        assert conv_resp.status_code == 201
        conv_id = conv_resp.json()["id"]

        # 2. Submit a lead
        lead_payload = {
            "conversation_id": conv_id,
            "customer_name": "Dr. Alice Smith",
            "email": "alice@alphapharma.com",
            "phone": "+1-555-0199",
            "notes": "Targeting 5 ml/min spray rate on drug-eluting stents.",
        }
        lead_resp = client.post("/customer/leads", json=lead_payload, headers=headers_a)
        assert lead_resp.status_code == 201
        lead_data = lead_resp.json()
        assert lead_data["customer_name"] == "Dr. Alice Smith"
        assert lead_data["company_name"] == "Alpha Pharma Ltd"
        assert lead_data["email"] == "alice@alphapharma.com"
        assert lead_data["phone"] == "+1-555-0199"
        assert lead_data["conversation_id"] == conv_id
        lead_id = lead_data["id"]

        # 3. Retrieve lead by conversation
        get_lead = client.get(f"/customer/leads/conversation/{conv_id}", headers=headers_a)
        assert get_lead.status_code == 200
        assert get_lead.json()["id"] == lead_id

        # 4. Idempotent re-submission updates the existing lead
        lead_payload["phone"] = "+1-555-0200"
        lead_resp2 = client.post("/customer/leads", json=lead_payload, headers=headers_a)
        assert lead_resp2.status_code == 201
        assert lead_resp2.json()["id"] == lead_id
        assert lead_resp2.json()["phone"] == "+1-555-0200"


def test_lead_company_isolation(conversation_context):
    with TestClient(app) as client_a:
        auth_a = login_user(client_a, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        # Alice creates a conversation
        conv_resp = client_a.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

    # Bob (from Beta Coatings) attempts to submit a lead for Alice's conversation
    with TestClient(app) as client_b:
        auth_b = login_user(client_b, "bob@betacoatings.com")
        headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}

        lead_payload = {
            "conversation_id": conv_id,
            "customer_name": "Bob Jones",
            "email": "bob@betacoatings.com",
        }
        res = client_b.post("/customer/leads", json=lead_payload, headers=headers_b)
        # Must fail with 404 because conversation belongs to Alpha Pharma
        assert res.status_code == 404


def test_admin_lead_management_and_csv_export(conversation_context):
    with TestClient(app) as client:
        # Create lead as Alice
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}
        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        # Potential formula injection string in notes / name
        lead_payload = {
            "conversation_id": conv_id,
            "customer_name": "=SUM(A1:A10)",
            "email": "alice@alphapharma.com",
            "notes": "+cmd|' /C calc'!A0",
        }
        client.post("/customer/leads", json=lead_payload, headers=headers_a)

        # Login as Admin
        auth_admin = login_user(client, "admin@wavenxd.com")
        headers_admin = {"X-CSRF-Token": auth_admin["csrf_token"]}

        # 1. Admin lists leads
        list_resp = client.get("/admin/leads", headers=headers_admin)
        assert list_resp.status_code == 200
        leads = list_resp.json()
        assert len(leads) >= 1
        target_lead = leads[0]
        lead_id = target_lead["id"]

        # 2. Admin retrieves lead detail
        detail_resp = client.get(f"/admin/leads/{lead_id}", headers=headers_admin)
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == lead_id

        # 3. Admin updates lead stage
        patch_resp = client.patch(
            f"/admin/leads/{lead_id}",
            json={"stage": LeadStage.QUALIFIED, "notes": "Verified requirements with engineering."},
            headers=headers_admin,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["stage"] == LeadStage.QUALIFIED

        # 4. Admin exports CSV and confirms formula injection protection
        csv_resp = client.get("/admin/leads/export/csv", headers=headers_admin)
        assert csv_resp.status_code == 200
        assert csv_resp.headers["Content-Type"].startswith("text/csv")
        csv_text = csv_resp.text
        # Formulas starting with '=' or '+' must be safely escaped with leading single quote
        assert "'=SUM(A1:A10)" in csv_text
        assert "'+cmd|' /C calc'!A0" in csv_text
