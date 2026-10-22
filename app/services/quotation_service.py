import html
from typing import Any
from bson import ObjectId
from fastapi import HTTPException, status

from app.models.common import utc_now
from app.models.lead import Lead
from app.models.user import User
from app.services.authorization import list_accessible_products_for_user
from app.services.conversation_service import get_customer_conversation
from app.services.recommendation_engine import evaluate_recommendations


async def generate_quotation_data(
    database: Any,
    customer_user: User,
    conversation_id: str | ObjectId,
) -> dict[str, Any]:
    """
    Generates a structured quotation draft from conversation requirements and authorized products.
    Strictly preserves canonical catalog truth: no invented prices, model numbers, or warranties.
    """
    conv = await get_customer_conversation(database, customer_user, conversation_id)

    comp_doc = await database.companies.find_one({"_id": customer_user.company_id})
    company_name = comp_doc.get("name") if comp_doc else "Client Company"

    lead_doc = await database.leads.find_one({
        "company_id": customer_user.company_id,
        "conversation_id": conv.id,
    })

    customer_name = customer_user.full_name or "Authorized Representative"
    email = customer_user.email
    phone = None
    notes = conv.requirements.notes

    if lead_doc:
        lead = Lead(**lead_doc)
        customer_name = lead.customer_name
        email = lead.email
        phone = lead.phone
        notes = lead.notes or notes

    candidate_products = await list_accessible_products_for_user(database, customer_user)
    rec_result = evaluate_recommendations(conv.requirements, candidate_products)

    short_id = str(conv.id)[-6:].upper()
    quote_ref = f"WNXD-QUOTE-{short_id}-{utc_now().strftime('%Y%m%d')}"

    confirmed_list = [
        {
            "product_id": p.product_id,
            "catalog_key": p.catalog_key,
            "name": p.product_name,
            "category": p.category,
            "reasons": p.reasons,
            "status": p.status.value,
            "technical_review_required": p.technical_review_required,
        }
        for p in rec_result.confirmed_recommendations
    ]

    potential_list = [
        {
            "product_id": p.product_id,
            "catalog_key": p.catalog_key,
            "name": p.product_name,
            "category": p.category,
            "reasons": p.reasons,
            "status": p.status.value,
            "technical_review_required": p.technical_review_required,
        }
        for p in rec_result.potential_matches
    ]

    reqs = conv.requirements
    return {
        "quote_reference": quote_ref,
        "title": "WaveNxD Technical Quotation Draft",
        "label": "Quotation Draft — Subject to Commercial Confirmation",
        "created_at": utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        "customer": {
            "name": customer_name,
            "company": company_name,
            "email": str(email),
            "phone": phone or "Not specified",
        },
        "requirements": {
            "industry": reqs.industry or "Not specified",
            "application": reqs.application or "Not specified",
            "fluid_description": reqs.fluid_description or "Not specified",
            "viscosity": f"{reqs.viscosity_cp:.1f} cP" if reqs.viscosity_cp is not None else "Unknown / Unspecified",
            "flow_rate": f"{reqs.flow_rate_ml_min:.2f} ml/min" if reqs.flow_rate_ml_min is not None else "Unknown / Unspecified",
            "droplet_size": f"{reqs.droplet_size_um:.1f} µm" if reqs.droplet_size_um is not None else "Standard / Unspecified",
            "spray_pattern": reqs.spray_pattern or "Standard",
            "feed_configuration": reqs.feed_configuration or "Standard",
            "notes": notes or "None",
        },
        "recommendation": {
            "outcome": rec_result.overall_outcome.value,
            "confirmed_products": confirmed_list,
            "potential_matches": potential_list,
            "technical_review_required": rec_result.technical_review_required,
            "summary_reasons": rec_result.summary_reasons,
            "limitations_and_gaps": rec_result.specification_gaps,
            "clarifications_required": rec_result.clarification_questions,
        },
        "pricing_status": "Price on Application — Final pricing and commercial terms require confirmation by WaveNxD.",
        "commercial_terms": [
            "1. Pricing Status: All equipment specifications are provided with 'Price on Application' (POA).",
            "2. Formal Commercial Review: Final pricing, payment terms, and delivery schedules require written engineering confirmation by WaveNxD Technologies Pvt. Ltd.",
            "3. Taxation & Logistics: Indicative proposals exclude GST/VAT, import duties, customs clearance, and transit freight unless specified in a formal purchase contract.",
            "4. Technical Validation: Fluid properties, viscosity, and chemical compatibility must be verified with Material Safety Data Sheets (MSDS) prior to equipment manufacturing.",
            "5. Engineering Review Policy: Candidate configurations flagged with 'Technical Review Required' or 'DRAFT' status are preliminary engineering indications and do not constitute an approved commercial offer.",
        ],
    }


def generate_quotation_html(quote_data: dict[str, Any]) -> str:
    """
    Generates a clean, accessible, print-ready HTML document for customer quotation review.
    Escapes all customer-provided strings to prevent XSS.
    """
    cust = quote_data["customer"]
    reqs = quote_data["requirements"]
    rec = quote_data["recommendation"]
    confirmed = rec["confirmed_products"]
    potential = rec["potential_matches"]

    confirmed_rows = ""
    if confirmed:
        for p in confirmed:
            reasons_html = "".join(f"<li>{html.escape(r)}</li>" for r in p["reasons"])
            confirmed_rows += f"""
            <tr>
              <td><strong>{html.escape(p['name'])}</strong><br><small style="color:#64748B;">Key: {html.escape(p.get('catalog_key') or 'N/A')}</small></td>
              <td>{html.escape(p.get('category') or 'ultrasonic_nozzle')}</td>
              <td><span style="color:#16A34A; font-weight:600;">CONFIRMED MATCH</span></td>
              <td><ul style="margin:0; padding-left:18px;">{reasons_html}</ul></td>
              <td style="font-weight:600; color:#2563EB;">Price on Application</td>
            </tr>
            """
    else:
        confirmed_rows = """
        <tr>
          <td colspan="5" style="text-align:center; padding:16px; color:#64748B;">
            No verified products currently meet all specified constraints within company entitlement scope.
          </td>
        </tr>
        """

    potential_rows = ""
    if potential:
        for p in potential:
            reasons_html = "".join(f"<li>{html.escape(r)}</li>" for r in p["reasons"])
            review_notice = "<br><span style='color:#DC2626; font-size:0.75rem;'>⚠️ Technical Verification Required</span>" if p.get("technical_review_required") else ""
            potential_rows += f"""
            <tr>
              <td><strong>{html.escape(p['name'])}</strong>{review_notice}</td>
              <td>{html.escape(p.get('category') or 'ultrasonic_nozzle')}</td>
              <td><span style="color:#D97706; font-weight:600;">NEEDS CONFIRMATION</span></td>
              <td><ul style="margin:0; padding-left:18px;">{reasons_html}</ul></td>
              <td style="font-weight:600; color:#64748B;">Subject to Review</td>
            </tr>
            """

    limitations_html = ""
    if rec["limitations_and_gaps"]:
        gaps = "".join(f"<li>{html.escape(g)}</li>" for g in rec["limitations_and_gaps"])
        limitations_html = f"""
        <div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:6px; padding:14px; margin-top:16px;">
          <h4 style="margin:0 0 6px 0; color:#92400E; font-size:0.875rem;">Technical Limitations &amp; Unconfirmed Assumptions:</h4>
          <ul style="margin:0; padding-left:18px; color:#B45309; font-size:0.8125rem;">{gaps}</ul>
        </div>
        """

    terms_html = "".join(f"<li style='margin-bottom:4px;'>{html.escape(t)}</li>" for t in quote_data["commercial_terms"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{html.escape(quote_data['quote_reference'])} — WaveNxD Technical Quotation Draft</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #0F172A;
      background: #FFFFFF;
      margin: 0;
      padding: 32px;
      line-height: 1.5;
    }}
    .no-print {{
      margin-bottom: 24px;
      display: flex;
      gap: 10px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      padding: 8px 16px;
      font-size: 0.875rem;
      font-weight: 600;
      border-radius: 6px;
      border: 1px solid transparent;
      cursor: pointer;
      text-decoration: none;
    }}
    .btn-primary {{
      background: #2563EB;
      color: #FFFFFF;
    }}
    .btn-secondary {{
      background: #F1F5F9;
      color: #0F172A;
      border-color: #CBD5E1;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      border-bottom: 2px solid #0F172A;
      padding-bottom: 16px;
      margin-bottom: 24px;
    }}
    .brand-title {{
      font-size: 1.5rem;
      font-weight: 800;
      color: #0F172A;
    }}
    .brand-subtitle {{
      font-size: 0.875rem;
      color: #64748B;
    }}
    .badge-draft {{
      display: inline-block;
      padding: 4px 10px;
      background: #FEF3C7;
      color: #92400E;
      font-weight: 700;
      font-size: 0.75rem;
      border-radius: 4px;
      border: 1px solid #F59E0B;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }}
    .panel {{
      background: #F8FAFC;
      border: 1px solid #E2E8F0;
      border-radius: 6px;
      padding: 16px;
    }}
    .panel h3 {{
      margin: 0 0 10px 0;
      font-size: 0.9375rem;
      color: #1E293B;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 0.875rem;
    }}
    th, td {{
      padding: 10px 12px;
      border: 1px solid #E2E8F0;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #F1F5F9;
      color: #334155;
      font-weight: 600;
    }}
    .poa-banner {{
      background: #EFF6FF;
      border: 1px solid #BFDBFE;
      color: #1D4ED8;
      font-weight: 600;
      padding: 12px 16px;
      border-radius: 6px;
      margin: 20px 0;
      font-size: 0.875rem;
    }}
    .footer-terms {{
      margin-top: 32px;
      border-top: 1px solid #E2E8F0;
      padding-top: 16px;
      font-size: 0.75rem;
      color: #64748B;
    }}
    @media print {{
      body {{ padding: 0; font-size: 11pt; }}
      .no-print {{ display: none !important; }}
      .panel {{ background: transparent; border: 1px solid #CBD5E1; }}
    }}
  </style>
</head>
<body>
  <div class="no-print">
    <button class="btn btn-primary" onclick="window.print()">🖨️ Print Quotation</button>
    <a class="btn btn-secondary" href="javascript:window.close()">Close Window</a>
  </div>

  <div class="header">
    <div>
      <div class="brand-title">WaveNxD Technologies Pvt. Ltd.</div>
      <div class="brand-subtitle">Precision Ultrasonic Atomization &amp; Dispensing Systems</div>
      <div style="margin-top: 8px;">
        <span class="badge-draft">{html.escape(quote_data['label'])}</span>
      </div>
    </div>
    <div style="text-align: right;">
      <div style="font-weight: 700; font-size: 1.125rem;">{html.escape(quote_data['quote_reference'])}</div>
      <div style="font-size: 0.8125rem; color: #64748B;">Date: {html.escape(quote_data['created_at'])}</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h3>Customer Account</h3>
      <div><strong>Company:</strong> {html.escape(cust['company'])}</div>
      <div><strong>Representative:</strong> {html.escape(cust['name'])}</div>
      <div><strong>Email:</strong> {html.escape(cust['email'])}</div>
      <div><strong>Phone:</strong> {html.escape(cust['phone'])}</div>
    </div>
    <div class="panel">
      <h3>Verified Process Requirements</h3>
      <div><strong>Target Application:</strong> {html.escape(reqs['application'])}</div>
      <div><strong>Coating Material / Fluid:</strong> {html.escape(reqs['fluid_description'])}</div>
      <div><strong>Operating Viscosity:</strong> {html.escape(reqs['viscosity'])}</div>
      <div><strong>Required Flow Rate:</strong> {html.escape(reqs['flow_rate'])}</div>
      <div><strong>Droplet Size Target:</strong> {html.escape(reqs['droplet_size'])}</div>
    </div>
  </div>

  <h3>Equipment Compatibility Evaluation</h3>
  <table>
    <thead>
      <tr>
        <th style="width:28%;">Product Candidate</th>
        <th style="width:18%;">Category</th>
        <th style="width:18%;">Compatibility Outcome</th>
        <th>Engineering Verification Notes</th>
        <th style="width:16%;">Unit Price</th>
      </tr>
    </thead>
    <tbody>
      {confirmed_rows}
      {potential_rows}
    </tbody>
  </table>

  {limitations_html}

  <div class="poa-banner">
    📌 Commercial Status: {html.escape(quote_data['pricing_status'])}
  </div>

  <div class="footer-terms">
    <h4 style="margin:0 0 6px 0; color:#334155; font-size:0.8125rem;">Terms of Engineering Quotation Draft:</h4>
    <ul style="margin:0; padding-left:18px;">
      {terms_html}
    </ul>
    <div style="margin-top: 12px; text-align: center; font-size: 0.6875rem; color: #94A3B8;">
      WaveNxD AI Sales Representative • Automated Quotation Draft • www.wavenxd.com
    </div>
  </div>
</body>
</html>
"""
