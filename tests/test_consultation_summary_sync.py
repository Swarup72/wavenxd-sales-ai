"""
Regression tests for WaveNxD Consultation Summary Synchronization and Message Formatting.

Validates the full lifecycle requested in Task Specification:
A. New conversation with no requirements shows appropriate empty state.
B. Customer providing application, liquid type, viscosity and target flow rate yields structured requirements.
C. Summary and recommendation update without page reload (retrievable via GET /customer/conversations/{id}).
D. Correct requirements shown when switching between two consultations.
E. A later question does not erase previously confirmed requirements.
F. Hypothetical flow-rate evaluation does not overwrite primary saved flow rate.
G. A no_match recommendation is displayed honestly without invented product recommendations.
H. Missing information is consistent with backend's structured result.
I. API failures display appropriate error and preserve existing state.
J. Message formatting renders tables, lists and linebreaks while escaping unsafe content.
K. Company isolation remains enforced.
"""

from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient

from app.domain.enums import ProductMatchStatus
from app.main import app
from app.services.llm_provider import LLMResponse, get_llm_provider
from tests.test_conversations import conversation_context, login_user


class MockConsultationLLM:
    """Mock LLM that echoes conversation context and maintains structured JSON requirements."""

    def __init__(self):
        self.last_system_prompt = None
        self.last_messages = None

    @property
    def provider_id(self):
        return "mock-consultation-llm"

    async def generate_chat_response(self, messages, system_prompt=None, correlation_id=None):
        self.last_system_prompt = system_prompt
        self.last_messages = messages
        user_text = messages[-1]["content"] if messages else ""

        # Respond appropriately to different prompts
        if "what if" in user_text.lower() or "hypothetical" in user_text.lower():
            return LLMResponse(
                content="Evaluating a hypothetical test target of 2 mL/min against our catalog for tablet coating. No standard nozzle is certified for tablet coating in pharmaceutical production.",
                model="mock-consultation-llm",
            )
        elif "warranty" in user_text.lower() or "lead time" in user_text.lower():
            return LLMResponse(
                content="WaveNxD ultrasonic nozzles come with a 1-year standard warranty. Lead time is 2-4 weeks. Your current specifications remain recorded.",
                model="mock-consultation-llm",
            )
        else:
            return LLMResponse(
                content="Thank you for providing your parameters. Here is our assessment:\n\n| Spec | Value |\n|---|---|\n| Application | Pharmaceutical tablet coating |\n| Viscosity | 15 cP |\n| Flow Rate | 10 mL/min |\n\nWe will evaluate this against our authorized catalog.",
                model="mock-consultation-llm",
            )


@pytest.fixture
def consultation_llm():
    mock = MockConsultationLLM()
    app.dependency_overrides[get_llm_provider] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_requirement_a_new_conversation_empty_state(conversation_context, consultation_llm):
    """A. A new conversation with no requirements shows an appropriate empty state."""
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # Create new conversation
        create_resp = client.post(
            "/customer/conversations",
            json={"title": "Empty Initial Consultation"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        data = create_resp.json()
        conv_id = data["id"]

        # Active requirements should be empty
        reqs = data["requirements"]
        assert reqs["application"] is None
        assert reqs["viscosity_cp"] is None
        assert reqs["flow_rate_ml_min"] is None
        assert reqs["fluid_description"] is None

        # Recommendation result should be present and indicate INSUFFICIENT_INFORMATION
        rec = data["recommendation_result"]
        assert rec is not None
        assert rec["overall_outcome"] == ProductMatchStatus.INSUFFICIENT_INFORMATION
        assert rec["confirmed_recommendations"] == []
        assert rec["recommended_product"] is None


def test_requirements_b_c_g_h_parameter_capture_and_summary_sync(conversation_context, consultation_llm):
    """
    B. Customer provides application, liquid type, viscosity and target flow rate -> structured requirements returned.
    C. Summary updates without page reload (retrieved via GET).
    G. No-match recommendation is displayed honestly without invented product.
    H. Missing information is consistent with backend result.
    """
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # Create conversation
        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        # Customer sends message with primary requirements:
        # Note: Tablet coating is NOT an authorized application in Alpha Pharma's catalog (which has Lab spray drying)
        msg_text = (
            "Application: pharmaceutical tablet coating\n"
            "Liquid type: water-based pharmaceutical coating solution\n"
            "Viscosity: 15 cP\n"
            "Initial target flow rate: 10 mL/min"
        )
        send_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": msg_text},
            headers=headers,
        )
        assert send_resp.status_code == 200
        send_data = send_resp.json()

        # B: Structured requirements returned in SendMessageResponse
        reqs = send_data["updated_requirements"]
        assert reqs["application"] == "pharmaceutical tablet coating"
        assert reqs["fluid_description"] == "water-based pharmaceutical coating solution"
        assert reqs["viscosity_cp"] == 15.0
        assert reqs["flow_rate_ml_min"] == 10.0

        # G: Outcome is NO_MATCH because tablet coating is not supported in the authorized catalog
        rec = send_data["recommendation_result"]
        assert rec is not None
        assert rec["overall_outcome"] == ProductMatchStatus.NO_MATCH
        assert rec["confirmed_recommendations"] == []
        assert rec["recommended_product"] is None
        assert any("meet the specified application" in r for r in rec["summary_reasons"])

        # H: Missing information is identified (droplet size, spray pattern, feed config)
        gaps = rec["specification_gaps"]
        assert any("droplet" in g.lower() for g in gaps)
        assert any("pattern" in g.lower() for g in gaps)
        assert any("feed" in g.lower() for g in gaps)

        # C: Verification via GET /customer/conversations/{id} returns identical structured state
        detail_resp = client.get(f"/customer/conversations/{conv_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["requirements"]["application"] == "pharmaceutical tablet coating"
        assert detail["requirements"]["flow_rate_ml_min"] == 10.0
        assert detail["recommendation_result"]["overall_outcome"] == ProductMatchStatus.NO_MATCH


def test_requirements_d_switching_between_two_consultations(conversation_context, consultation_llm):
    """D. Correct requirements are shown when switching between two consultations."""
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # Consultation 1: Tablet coating at 10 mL/min
        c1 = client.post("/customer/conversations", json={"title": "Consultation 1"}, headers=headers).json()
        client.post(
            f"/customer/conversations/{c1['id']}/messages",
            json={"content": "Application: pharmaceutical tablet coating\nViscosity: 15 cP\nFlow rate: 10 mL/min"},
            headers=headers,
        )

        # Consultation 2: Lab spray drying at 2 mL/min (which matches Alpha Pharma's catalog!)
        c2 = client.post("/customer/conversations", json={"title": "Consultation 2"}, headers=headers).json()
        client.post(
            f"/customer/conversations/{c2['id']}/messages",
            json={"content": "Application: Lab spray drying\nViscosity: 5 cP\nFlow rate: 2 mL/min"},
            headers=headers,
        )

        # Switch to Consultation 1: Verify tablet coating 10 mL/min, no match
        get_c1 = client.get(f"/customer/conversations/{c1['id']}").json()
        assert get_c1["requirements"]["application"] == "pharmaceutical tablet coating"
        assert get_c1["requirements"]["flow_rate_ml_min"] == 10.0
        assert get_c1["recommendation_result"]["overall_outcome"] == ProductMatchStatus.NO_MATCH

        # Switch to Consultation 2: Verify spray drying 2 mL/min, confirmed match!
        get_c2 = client.get(f"/customer/conversations/{c2['id']}").json()
        assert get_c2["requirements"]["application"] == "Lab spray drying"
        assert get_c2["requirements"]["flow_rate_ml_min"] == 2.0
        assert get_c2["recommendation_result"]["overall_outcome"] == ProductMatchStatus.MATCH
        assert get_c2["recommendation_result"]["recommended_product"] is not None
        assert get_c2["recommendation_result"]["recommended_product"]["catalog_key"] == "standard-nozzle-60khz"


def test_requirements_e_and_f_hypothetical_and_question_preservation(conversation_context, consultation_llm):
    """
    E. A later question does not erase previously confirmed requirements.
    F. A hypothetical flow-rate evaluation (2 mL/min) does not silently overwrite primary saved target (10 mL/min).
    """
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # 1. Establish confirmed requirements
        conv_resp = client.post("/customer/conversations", headers=headers)
        conv_id = conv_resp.json()["id"]

        init_msg = (
            "Application: pharmaceutical tablet coating\n"
            "Liquid type: water-based pharmaceutical coating solution\n"
            "Viscosity: 15 cP\n"
            "Initial target flow rate: 10 mL/min"
        )
        client.post(f"/customer/conversations/{conv_id}/messages", json={"content": init_msg}, headers=headers)

        # 2. Customer asks a hypothetical question with 2 mL/min test target:
        hypo_msg = "Later hypothetical test target: 2 mL/min. What if we test at 2 mL/min?"
        hypo_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": hypo_msg},
            headers=headers,
        )
        assert hypo_resp.status_code == 200
        hypo_data = hypo_resp.json()

        # F: The primary saved target flow rate MUST REMAIN 10.0 mL/min!
        assert hypo_data["updated_requirements"]["flow_rate_ml_min"] == 10.0
        assert hypo_data["updated_requirements"]["application"] == "pharmaceutical tablet coating"
        assert hypo_data["updated_requirements"]["viscosity_cp"] == 15.0

        # Recommendation result evaluates the hypothetical scenario (2 mL/min with tablet coating) -> NO_MATCH
        assert hypo_data["recommendation_result"]["overall_outcome"] == ProductMatchStatus.NO_MATCH

        # 3. Customer asks a general follow-up question (Point E):
        q_msg = "What warranty is provided and what is the typical lead time?"
        q_resp = client.post(
            f"/customer/conversations/{conv_id}/messages",
            json={"content": q_msg},
            headers=headers,
        )
        assert q_resp.status_code == 200
        q_data = q_resp.json()

        # E: All previously confirmed requirements are preserved completely
        assert q_data["updated_requirements"]["application"] == "pharmaceutical tablet coating"
        assert q_data["updated_requirements"]["fluid_description"] == "water-based pharmaceutical coating solution"
        assert q_data["updated_requirements"]["viscosity_cp"] == 15.0
        assert q_data["updated_requirements"]["flow_rate_ml_min"] == 10.0

        # Also verified in persisted conversation
        stored_detail = client.get(f"/customer/conversations/{conv_id}").json()
        assert stored_detail["requirements"]["flow_rate_ml_min"] == 10.0
        assert stored_detail["requirements"]["application"] == "pharmaceutical tablet coating"


def test_requirement_k_company_isolation_on_conversations_and_recommendations(conversation_context):
    """K. Company isolation remains enforced when retrieving conversations, requirements and recommendations."""
    with TestClient(app) as client:
        # Alice (Alpha Pharma) creates a consultation
        auth_a = login_user(client, "alice@alphapharma.com")
        headers_a = {"X-CSRF-Token": auth_a["csrf_token"]}
        conv_a = client.post("/customer/conversations", headers=headers_a).json()
        conv_a_id = conv_a["id"]

        # Bob (Beta Coatings) logs in
        auth_b = login_user(client, "bob@betacoatings.com")
        headers_b = {"X-CSRF-Token": auth_b["csrf_token"]}

        # Bob cannot retrieve Alice's conversation details (404 Not Found)
        bob_get = client.get(f"/customer/conversations/{conv_a_id}", headers=headers_b)
        assert bob_get.status_code == 404

        # Bob cannot send messages to Alice's conversation
        bob_send = client.post(
            f"/customer/conversations/{conv_a_id}/messages",
            json={"content": "Attempting cross-company message"},
            headers=headers_b,
        )
        assert bob_send.status_code == 404

        # Bob cannot evaluate recommendations on Alice's conversation
        bob_rec = client.post(
            f"/customer/conversations/{conv_a_id}/recommendations",
            headers=headers_b,
        )
        assert bob_rec.status_code == 404


def test_requirement_i_api_failure_preserves_state(conversation_context, consultation_llm):
    """I. API failures display an appropriate error rather than falsely clearing confirmed requirements."""
    with TestClient(app) as client:
        auth = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth["csrf_token"]}

        # 1. Establish confirmed requirements
        conv = client.post("/customer/conversations", headers=headers).json()
        conv_id = conv["id"]

        init_msg = (
            "Application: pharmaceutical tablet coating\n"
            "Viscosity: 15 cP\n"
            "Flow rate: 10 mL/min"
        )
        client.post(f"/customer/conversations/{conv_id}/messages", json={"content": init_msg}, headers=headers)

        # 2. Simulate LLM service failure
        from app.services.llm_provider import LLMProviderUnavailableError

        class FailingLLM:
            @property
            def provider_id(self):
                return "failing-llm"

            async def generate_chat_response(self, messages, system_prompt=None, correlation_id=None):
                raise LLMProviderUnavailableError("Upstream AI model unavailable")

        app.dependency_overrides[get_llm_provider] = lambda: FailingLLM()
        try:
            fail_resp = client.post(
                f"/customer/conversations/{conv_id}/messages",
                json={"content": "Can we test another parameter?"},
                headers=headers,
            )
            assert fail_resp.status_code == 503
            assert "temporarily unavailable" in fail_resp.json()["detail"].lower()

            # Ensure previous requirements are NOT lost or overwritten with empty state
            detail = client.get(f"/customer/conversations/{conv_id}").json()
            assert detail["requirements"]["application"] == "pharmaceutical tablet coating"
            assert detail["requirements"]["viscosity_cp"] == 15.0
            assert detail["requirements"]["flow_rate_ml_min"] == 10.0
        finally:
            app.dependency_overrides[get_llm_provider] = lambda: consultation_llm


def test_requirement_j_message_formatting_markdown_and_escaping():
    """J. Message formatting renders tables, lists and line breaks correctly while escaping unsafe content."""
    import subprocess
    import json

    node_script = """
    import { renderMarkdown } from './app/static/js/customer/message-renderer.js';

    const tableInput = '| Spec | Value |\\n|---|---|\\n| Viscosity | 15 cP |\\n| Flow Rate | 10 mL/min |';
    const tableOut = renderMarkdown(tableInput);

    const brInput = 'Line 1<br>Line 2<br/>Line 3';
    const brOut = renderMarkdown(brInput);

    const listInput = 'Requirements:\\n- Spec A\\n- Spec B';
    const listOut = renderMarkdown(listInput);

    const xssInput = '<script>alert("xss")</script><img src=x onerror=alert(1)>';
    const xssOut = renderMarkdown(xssInput);

    console.log(JSON.stringify({ tableOut, brOut, listOut, xssOut }));
    """

    res = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)

    # 1. Table rendered cleanly without literal pipes or raw markdown separator
    assert "<table class=\"markdown-table\">" in data["tableOut"]
    assert "<th>Spec</th><th>Value</th>" in data["tableOut"]
    assert "<td>Viscosity</td><td>15 cP</td>" in data["tableOut"]
    assert "|---|---|" not in data["tableOut"]
    assert "| Spec | Value |" not in data["tableOut"]

    # 2. Raw <br> normalized without literal &lt;br&gt;
    assert "&lt;br&gt;" not in data["brOut"]
    assert "&lt;br/&gt;" not in data["brOut"]
    assert "<br>" in data["brOut"]

    # 3. Lists parsed with <ul> and <li>
    assert "<ul><li>Spec A</li><li>Spec B</li></ul>" in data["listOut"]

    # 4. Unsafe HTML strictly escaped
    assert "<script>" not in data["xssOut"]
    assert "&lt;script&gt;alert" in data["xssOut"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in data["xssOut"]


def test_consultation_summary_card_rendering_all_three_states():
    """Regression test: Recommended Product card handles insufficient, match, and no_match consistently."""
    import json
    import subprocess

    node_script = """
    import { renderConsultationSummary } from './app/static/js/customer/consultation-summary.js';

    function createMockElement(id) {
      return {
        id,
        style: { display: '' },
        classList: {
          classes: [],
          add(c) { this.classes.push(c); },
          remove(c) { this.classes = this.classes.filter(x => x !== c); },
          contains(c) { return this.classes.includes(c); }
        },
        className: '',
        textContent: '',
        innerHTML: '',
      };
    }

    function createElements() {
      return {
        matchStatusBadge: createMockElement('matchStatusBadge'),
        matchSummaryText: createMockElement('matchSummaryText'),
        reviewWarningPill: createMockElement('reviewWarningPill'),
        knownReqsContainer: createMockElement('knownReqsContainer'),
        missingInfoAccordion: createMockElement('missingInfoAccordion'),
        missingInfoCount: createMockElement('missingInfoCount'),
        missingInfoList: createMockElement('missingInfoList'),
        compactProductEmpty: createMockElement('compactProductEmpty'),
        compactProductContent: createMockElement('compactProductContent'),
        compactProdName: createMockElement('compactProdName'),
        compactProdKey: createMockElement('compactProdKey'),
        compactProdMatchBadge: createMockElement('compactProdMatchBadge'),
        compactProdExplanation: createMockElement('compactProdExplanation'),
      };
    }

    // State 1: Insufficient Information
    const el1 = createElements();
    renderConsultationSummary({
      overall_outcome: 'insufficient_information',
      confirmed_recommendations: [],
      potential_matches: [],
      recommended_product: null,
      summary_reasons: ['Please specify flow rate or viscosity.']
    }, el1, {});

    // State 2: Confirmed Match
    const el2 = createElements();
    renderConsultationSummary({
      overall_outcome: 'match',
      confirmed_recommendations: [{
        product_name: 'Precision Ultrasonic Nozzle WNX-100',
        catalog_key: 'WNX-100',
        reasons: ['Process specifications verified.']
      }],
      recommended_product: {
        product_name: 'Precision Ultrasonic Nozzle WNX-100',
        catalog_key: 'WNX-100',
        reasons: ['Process specifications verified.']
      },
      summary_reasons: ['Found 1 confirmed recommendation.']
    }, el2, { flow_rate_ml_min: 10, viscosity_cp: 15 });

    // State 3: No Match (Active requirements present, no eligible product)
    const el3 = createElements();
    renderConsultationSummary({
      overall_outcome: 'no_match',
      confirmed_recommendations: [],
      potential_matches: [],
      unmatched_candidates: [{ product_name: 'Standard Nozzle', status: 'no_match' }],
      recommended_product: null,
      summary_reasons: ['None of your company\\'s assigned catalog products meet the specified application and operational requirements.']
    }, el3, {
      application: 'pharmaceutical tablet coating',
      fluid_description: 'water-based pharmaceutical coating solution',
      viscosity_cp: 15,
      flow_rate_ml_min: 10
    });

    console.log(JSON.stringify({
      state1: {
        emptyDisplay: el1.compactProductEmpty.style.display,
        contentDisplay: el1.compactProductContent.style.display,
        emptyText: el1.compactProductEmpty.textContent,
        badgeText: el1.matchStatusBadge.textContent,
      },
      state2: {
        emptyDisplay: el2.compactProductEmpty.style.display,
        contentDisplay: el2.compactProductContent.style.display,
        prodName: el2.compactProdName.textContent,
        prodBadge: el2.compactProdMatchBadge.textContent,
        badgeText: el2.matchStatusBadge.textContent,
      },
      state3: {
        emptyDisplay: el3.compactProductEmpty.style.display,
        contentDisplay: el3.compactProductContent.style.display,
        prodName: el3.compactProdName.textContent,
        prodBadge: el3.compactProdMatchBadge.textContent,
        badgeClass: el3.compactProdMatchBadge.className,
        badgeText: el3.matchStatusBadge.textContent,
        summaryText: el3.matchSummaryText.textContent,
        explanation: el3.compactProdExplanation.textContent,
        reqsHtml: el3.knownReqsContainer.innerHTML,
      }
    }));
    """

    res = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)

    # State 1: Insufficient Information
    assert data["state1"]["emptyDisplay"] == "block"
    assert data["state1"]["contentDisplay"] == "none"
    assert "Awaiting sufficient technical parameters" in data["state1"]["emptyText"]
    assert data["state1"]["badgeText"] == "INSUFFICIENT INFORMATION"

    # State 2: Match
    assert data["state2"]["emptyDisplay"] == "none"
    assert data["state2"]["contentDisplay"] == "block"
    assert data["state2"]["prodName"] == "Precision Ultrasonic Nozzle WNX-100"
    assert data["state2"]["prodBadge"] == "CONFIRMED MATCH"
    assert data["state2"]["badgeText"] == "CONFIRMED MATCH"

    # State 3: No Match (Crucial regression check)
    assert data["state3"]["emptyDisplay"] == "none", "Waiting placeholder MUST be hidden on NO MATCH"
    assert data["state3"]["contentDisplay"] == "block", "Product card MUST be displayed on NO MATCH"
    assert data["state3"]["prodName"] == "No Compatible Nozzle"
    assert data["state3"]["prodBadge"] == "NO MATCH"
    assert "nomatch" in data["state3"]["badgeClass"]
    assert data["state3"]["badgeText"] == "NO COMPATIBLE NOZZLE"
    assert "None of your company's assigned catalog products" in data["state3"]["explanation"]
    assert "Flow:</strong> 10 ml/min" in data["state3"]["reqsHtml"]
    assert "Viscosity:</strong> 15 cP" in data["state3"]["reqsHtml"]

