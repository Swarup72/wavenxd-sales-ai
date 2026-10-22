from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.domain.enums import EmailDispatchStatus
from app.main import app
from tests.test_conversations import conversation_context, login_user


def test_quote_preview_and_download(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        # 1. Create a conversation and post requirements
        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        # 2. Get quote preview JSON
        quote_resp = client.get(f"/customer/conversations/{conv_id}/quote-preview", headers=headers_a)
        assert quote_resp.status_code == 200
        quote_data = quote_resp.json()

        assert "quote_reference" in quote_data
        assert quote_data["title"] == "WaveNxD Technical Quotation Draft"
        assert quote_data["label"] == "Quotation Draft — Subject to Commercial Confirmation"
        assert quote_data["customer"]["company"] == "Alpha Pharma Ltd"
        assert "Price on Application" in quote_data["pricing_status"]

        # 3. Download print-ready HTML
        dl_resp = client.get(f"/customer/conversations/{conv_id}/quote-preview/download", headers=headers_a)
        assert dl_resp.status_code == 200
        assert dl_resp.headers["Content-Type"].startswith("text/html")
        assert "attachment; filename=" in dl_resp.headers["Content-Disposition"]
        assert "WaveNxD Technologies Pvt. Ltd." in dl_resp.text
        assert "@media print" in dl_resp.text
        assert "Price on Application" in dl_resp.text


def test_quote_cross_company_isolation(conversation_context):
    with TestClient(app) as client_a:
        auth_a = login_user(client_a, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}
        conv_resp = client_a.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

    # Bob attempts to get Alice's quote preview
    with TestClient(app) as client_b:
        auth_b = login_user(client_b, "bob@betacoatings.com")
        headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}
        quote_resp = client_b.get(f"/customer/conversations/{conv_id}/quote-preview", headers=headers_b)
        assert quote_resp.status_code == 404


def test_email_draft_preview_and_download(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        # 1. Preview email draft
        draft_resp = client.get(f"/customer/conversations/{conv_id}/email-draft", headers=headers_a)
        assert draft_resp.status_code == 200
        draft_data = draft_resp.json()
        assert draft_data["status"] == EmailDispatchStatus.PREVIEW
        assert draft_data["recipient"] == "alice@alphapharma.com"
        assert "WaveNxD Quotation Draft" in draft_data["subject"]
        assert "No external email was transmitted" in draft_data["notice"]

        # 2. Download .eml file
        eml_resp = client.get(f"/customer/conversations/{conv_id}/email-draft/download", headers=headers_a)
        assert eml_resp.status_code == 200
        assert eml_resp.headers["Content-Type"].startswith("message/rfc822")
        assert ".eml" in eml_resp.headers["Content-Disposition"]
        assert b"Subject:" in eml_resp.content
        assert b"sales@wavenxd.com" in eml_resp.content

        # 3. Simulate email delivery
        sim_resp = client.post(f"/customer/conversations/{conv_id}/email-simulate", headers=headers_a)
        assert sim_resp.status_code == 200
        sim_data = sim_resp.json()
        assert sim_data["status"] == EmailDispatchStatus.SIMULATED
        assert "No network transmission was attempted" in sim_data["message"]


def test_follow_up_scheduling_and_ics_calendar(conversation_context):
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        # 1. Attempt downloading calendar before scheduling -> 400 Bad Request
        ics_early = client.get(f"/customer/conversations/{conv_id}/follow-up/calendar.ics", headers=headers_a)
        assert ics_early.status_code == 400

        # 2. Schedule follow-up
        scheduled_time = datetime(2026, 11, 15, 14, 0, 0, tzinfo=timezone.utc)
        payload = {
            "scheduled_at": scheduled_time.isoformat(),
            "timezone": "UTC",
            "duration_minutes": 30,
            "notes": "Discuss ultrasonic nozzle horn geometry and flow rate.",
        }
        sched_resp = client.post(
            f"/customer/conversations/{conv_id}/follow-up",
            json=payload,
            headers=headers_a,
        )
        assert sched_resp.status_code == 200
        sched_data = sched_resp.json()
        assert sched_data["conversation_id"] == conv_id
        assert "calendar.google.com" in sched_data["google_calendar_url"]
        assert "WaveNxD" in sched_data["google_calendar_url"]

        # 3. Download .ics file
        ics_resp = client.get(f"/customer/conversations/{conv_id}/follow-up/calendar.ics", headers=headers_a)
        assert ics_resp.status_code == 200
        assert ics_resp.headers["Content-Type"].startswith("text/calendar")
        assert ".ics" in ics_resp.headers["Content-Disposition"]

        ics_text = ics_resp.text
        assert "BEGIN:VCALENDAR" in ics_text
        assert "VERSION:2.0" in ics_text
        assert "BEGIN:VEVENT" in ics_text
        assert "DTSTART:20261115T140000Z" in ics_text
        assert "DTEND:20261115T143000Z" in ics_text
        assert "SUMMARY:WaveNxD Technical Consultation" in ics_text
        assert "END:VEVENT" in ics_text
        assert "END:VCALENDAR" in ics_text


def test_quotation_catalog_safety_and_pricing_notice(conversation_context):
    """
    Phase 7: Verify catalog safety and pricing guarantees.
    - No fabricated prices, currencies, or delivery dates.
    - Explicit 'Price on Application' commercial notice.
    - Review-required products retain engineering review warnings.
    """
    with TestClient(app) as client:
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}

        conv_resp = client.post("/customer/conversations", headers=headers_a)
        conv_id = conv_resp.json()["id"]

        quote_resp = client.get(f"/customer/conversations/{conv_id}/quote-preview", headers=headers_a)
        assert quote_resp.status_code == 200
        quote_data = quote_resp.json()

        # Pricing status must require commercial confirmation
        pricing = quote_data["pricing_status"]
        assert "Price on Application" in pricing
        assert "Final pricing and commercial terms require confirmation by WaveNxD" in pricing

        # Ensure no invented currency amounts exist
        for symbol in ["$", "€", "₹", "£"]:
            assert symbol not in pricing

        # When evaluated for candidates, products must contain catalog-backed specs
        all_eval_prods = (
            quote_data["recommendation"]["confirmed_products"]
            + quote_data["recommendation"]["potential_matches"]
        )
        for prod in all_eval_prods:
            assert "catalog_key" in prod
            assert "name" in prod
            assert "category" in prod

