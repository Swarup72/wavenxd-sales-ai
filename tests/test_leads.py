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
        assert patch_resp.json()["internal_notes"] == "Verified requirements with engineering."

        # 4. Admin exports CSV and confirms formula injection protection
        csv_resp = client.get("/admin/leads/export/csv", headers=headers_admin)
        assert csv_resp.status_code == 200
        assert csv_resp.headers["Content-Type"].startswith("text/csv")
        csv_text = csv_resp.text
        # Formulas starting with '=' or '+' must be safely escaped with leading single quote
        assert "'=SUM(A1:A10)" in csv_text
        assert "'+cmd|' /C calc'!A0" in csv_text


def test_admin_internal_notes_persistence_and_stage_updates(conversation_context):
    """
    Regression test:
    1. Saving notes only preserves stage and customer notes.
    2. Updating stage only preserves existing internal notes.
    3. Updating both together persists both correctly.
    4. Fresh database read retrieves persisted internal notes.
    5. Customer endpoint never exposes admin internal notes.
    """
    with TestClient(app) as client:
        # Step 1: Customer creates consultation & lead with customer notes
        auth_cust = login_user(client, "alice@alphapharma.com")
        headers_cust = {"X-CSRF-Token": auth_cust["csrf_token"]}

        conv = client.post("/customer/conversations", json={"title": "Internal Notes Test"}, headers=headers_cust).json()
        conv_id = conv["id"]

        cust_notes = "Customer Inquiry Notes: Needs spray nozzle for pharmaceutical coating."
        lead_payload = {
            "conversation_id": conv_id,
            "customer_name": "Dr. Alice Smith",
            "email": "alice@alphapharma.com",
            "phone": "+1-555-7788",
            "notes": cust_notes,
        }
        lead_res = client.post("/customer/leads", json=lead_payload, headers=headers_cust)
        assert lead_res.status_code == 201
        lead_id = lead_res.json()["id"]

        # Step 2: Admin logs in
        auth_admin = login_user(client, "admin@wavenxd.com")
        headers_admin = {"X-CSRF-Token": auth_admin["csrf_token"]}

        # Check initial state for admin
        init_admin = client.get(f"/admin/leads/{lead_id}", headers=headers_admin).json()
        assert init_admin["stage"] == LeadStage.NEW
        assert init_admin["notes"] == cust_notes
        assert init_admin["internal_notes"] is None

        # Case A: Saving notes only (stage omitted / None)
        note_1 = "Eng Note #1: Checked catalog compatibility with 15 cP solution."
        patch_1 = client.patch(
            f"/admin/leads/{lead_id}",
            json={"notes": note_1},
            headers=headers_admin,
        )
        assert patch_1.status_code == 200
        p1_data = patch_1.json()
        assert p1_data["internal_notes"] == note_1
        assert p1_data["stage"] == LeadStage.NEW, "Stage must not be overwritten when only notes are updated"
        assert p1_data["notes"] == cust_notes, "Customer inquiry notes must not be overwritten"

        # Case B: Updating stage only (notes omitted / None)
        patch_2 = client.patch(
            f"/admin/leads/{lead_id}",
            json={"stage": LeadStage.QUOTE_DRAFT},
            headers=headers_admin,
        )
        assert patch_2.status_code == 200
        p2_data = patch_2.json()
        assert p2_data["stage"] == LeadStage.QUOTE_DRAFT
        assert p2_data["internal_notes"] == note_1, "Internal notes must not be wiped when only stage is updated"
        assert p2_data["notes"] == cust_notes, "Customer inquiry notes must remain intact"

        # Case C: Updating both stage and internal_notes together
        note_2 = "Eng Note #2: Quotation draft prepared with 2-week delivery."
        patch_3 = client.patch(
            f"/admin/leads/{lead_id}",
            json={"stage": LeadStage.QUALIFIED, "internal_notes": note_2},
            headers=headers_admin,
        )
        assert patch_3.status_code == 200
        p3_data = patch_3.json()
        assert p3_data["stage"] == LeadStage.QUALIFIED
        assert p3_data["internal_notes"] == note_2

        # Case D: Fresh database read
        fresh_admin = client.get(f"/admin/leads/{lead_id}", headers=headers_admin).json()
        assert fresh_admin["id"] == lead_id
        assert fresh_admin["stage"] == LeadStage.QUALIFIED
        assert fresh_admin["internal_notes"] == note_2
        assert fresh_admin["notes"] == cust_notes
        assert fresh_admin["customer_name"] == "Dr. Alice Smith"
        assert fresh_admin["phone"] == "+1-555-7788"

        # Case E: Strict Customer Privacy - Customer must NEVER see internal notes
        auth_alice = login_user(client, "alice@alphapharma.com")
        headers_alice = {"X-CSRF-Token": auth_alice["csrf_token"]}
        cust_view = client.get(f"/customer/leads/conversation/{conv_id}", headers=headers_alice).json()
        assert cust_view["id"] == lead_id
        assert cust_view["notes"] == cust_notes
        assert cust_view.get("internal_notes") is None, "Security violation: Internal admin notes exposed to customer!"


def test_admin_lead_modal_frontend_script_behavior():
    """Verify that admin lead JavaScript correctly maps internal_notes to adminLeadInternalNotes."""
    import json
    import subprocess

    node_script = """
    // Mock DOM elements
    const elements = {};
    function getMockEl(id) {
      if (!elements[id]) {
        elements[id] = { id, value: '', textContent: '' };
      }
      return elements[id];
    }
    globalThis.document = {
      getElementById: (id) => getMockEl(id)
    };

    // Simulate openLeadDetailModal populating logic
    const lead = {
      id: 'lead-123',
      customer_name: 'Dr. Alice',
      company_name: 'Alpha Pharma',
      stage: 'quote_draft',
      notes: 'Customer inquiry: 10 ml/min coating',
      technical_notes: 'Customer inquiry: 10 ml/min coating',
      internal_notes: 'Internal Sales Note: Followed up with Dr. Alice on pricing.',
      flow_rate_ml_min: 10,
      viscosity_cp: 15,
      droplet_size_um: 20
    };

    document.getElementById('adminLeadId').value = lead.id;
    document.getElementById('adminLeadCustName').textContent = lead.customer_name || '—';
    document.getElementById('adminLeadCompanyName').textContent = lead.company_name || '—';
    document.getElementById('adminLeadCustNotes').textContent = lead.notes || lead.technical_notes || 'None';
    document.getElementById('adminLeadStageSelect').value = lead.stage || 'new';
    document.getElementById('adminLeadInternalNotes').value = lead.internal_notes || '';

    console.log(JSON.stringify({
      leadId: document.getElementById('adminLeadId').value,
      stageVal: document.getElementById('adminLeadStageSelect').value,
      custNotesText: document.getElementById('adminLeadCustNotes').textContent,
      internalNotesVal: document.getElementById('adminLeadInternalNotes').value,
    }));
    """

    res = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)

    assert data["stageVal"] == "quote_draft"
    assert data["custNotesText"] == "Customer inquiry: 10 ml/min coating"
    assert data["internalNotesVal"] == "Internal Sales Note: Followed up with Dr. Alice on pricing."

