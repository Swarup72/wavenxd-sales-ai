import html
from email.message import EmailMessage
from typing import Any

from app.domain.enums import EmailDispatchStatus


def create_quotation_email_draft(
    quote_data: dict[str, Any],
    recipient_email: str,
) -> tuple[dict[str, Any], bytes]:
    """
    Constructs an RFC 822 compliant email draft (.eml) using the Python standard library.
    Ensures complete transparency: status is strictly PREVIEW, never claiming to be sent.
    """
    quote_ref = quote_data.get("quote_reference", "WNXD-QUOTE")
    cust = quote_data.get("customer", {})
    reqs = quote_data.get("requirements", {})
    rec = quote_data.get("recommendation", {})
    confirmed = rec.get("confirmed_products", [])
    potential = rec.get("potential_matches", [])

    prod_name = confirmed[0]["name"] if confirmed else (potential[0]["name"] if potential else "Ultrasonic Spray Inquiry")
    subject = f"WaveNxD Quotation Draft [{quote_ref}] — {prod_name}"

    # Plaintext version
    plain_lines = [
        f"Dear {cust.get('name', 'Valued Customer')},",
        "",
        f"Thank you for consulting with WaveNxD AI Sales Representative regarding your application at {cust.get('company', 'your company')}.",
        "",
        "Attached below is your technical quotation draft for precision ultrasonic atomization equipment:",
        f"Quotation Reference: {quote_ref}",
        f"Date Generated: {quote_data.get('created_at', '')}",
        "",
        "--- VERIFIED PROCESS SPECIFICATIONS ---",
        f"• Target Application: {reqs.get('application', 'N/A')}",
        f"• Coating Material / Fluid: {reqs.get('fluid_description', 'N/A')}",
        f"• Operating Viscosity: {reqs.get('viscosity', 'N/A')}",
        f"• Required Flow Rate: {reqs.get('flow_rate', 'N/A')}",
        f"• Droplet Size Target: {reqs.get('droplet_size', 'N/A')}",
        "",
        "--- RECOMMENDED PRODUCT CANDIDATES ---",
    ]

    if confirmed:
        for p in confirmed:
            plain_lines.append(f"• [CONFIRMED MATCH] {p['name']} ({p.get('category', 'ultrasonic_nozzle')})")
            for r in p.get("reasons", []):
                plain_lines.append(f"    - {r}")
            plain_lines.append(f"    - Indicative Pricing: Price on Application (POA)")
    elif potential:
        for p in potential:
            plain_lines.append(f"• [NEEDS CONFIRMATION] {p['name']} (Technical review required)")
            for r in p.get("reasons", []):
                plain_lines.append(f"    - {r}")
    else:
        plain_lines.append("• No verified products in current catalog entitlement meet all constraints.")

    plain_lines.extend([
        "",
        "--- COMMERCIAL STATUS & NEXT STEPS ---",
        "Commercial Notice: Price on Application (POA). Final pricing, formal pro-forma invoice, and delivery schedules require written engineering confirmation by WaveNxD Technologies Pvt. Ltd.",
        "",
        "To finalize this inquiry or schedule a video review with a WaveNxD sales engineer, reply directly or download the attached quotation.",
        "",
        "Warm regards,",
        "WaveNxD Technical Sales Team",
        "WaveNxD Technologies Pvt. Ltd.",
        "sales@wavenxd.com | www.wavenxd.com",
    ])
    plain_body = "\n".join(plain_lines)

    # HTML version
    confirmed_html = "".join(
        f"<li><strong>{html.escape(p['name'])}</strong> — <span style='color:#16A34A;font-weight:600;'>CONFIRMED MATCH</span> (Price on Application)</li>"
        for p in confirmed
    ) or "<li>No confirmed product candidates in catalog.</li>"

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif; color:#0F172A; line-height:1.5;">
  <div style="max-width:600px; margin:0 auto; padding:20px; border:1px solid #E2E8F0; border-radius:8px;">
    <h2 style="color:#0F172A; margin-top:0;">WaveNxD Technologies Pvt. Ltd.</h2>
    <div style="background:#FEF3C7; border:1px solid #F59E0B; color:#92400E; padding:8px 12px; border-radius:4px; font-weight:bold; font-size:12px; margin-bottom:16px;">
      QUOTATION DRAFT — SUBJECT TO COMMERCIAL CONFIRMATION
    </div>
    <p>Dear {html.escape(cust.get('name', 'Valued Customer'))},</p>
    <p>Here is your technical quotation draft (Ref: <strong>{html.escape(quote_ref)}</strong>) generated from your consultation on ultrasonic atomization systems.</p>
    
    <div style="background:#F8FAFC; border:1px solid #E2E8F0; padding:12px; border-radius:6px; margin:16px 0;">
      <h4 style="margin:0 0 8px 0; color:#334155;">Application Parameters:</h4>
      <ul style="margin:0; padding-left:20px; font-size:13px;">
        <li><strong>Application:</strong> {html.escape(reqs.get('application', 'N/A'))}</li>
        <li><strong>Fluid:</strong> {html.escape(reqs.get('fluid_description', 'N/A'))}</li>
        <li><strong>Viscosity:</strong> {html.escape(reqs.get('viscosity', 'N/A'))}</li>
        <li><strong>Flow Rate:</strong> {html.escape(reqs.get('flow_rate', 'N/A'))}</li>
      </ul>
    </div>

    <h4>Recommended Equipment:</h4>
    <ul style="padding-left:20px;">
      {confirmed_html}
    </ul>

    <div style="background:#EFF6FF; border:1px solid #BFDBFE; color:#1D4ED8; padding:10px 14px; border-radius:6px; font-size:13px; margin:16px 0;">
      <strong>Pricing Status:</strong> Price on Application — Commercial pricing and terms require review and confirmation by WaveNxD sales operations.
    </div>

    <p style="font-size:13px; color:#64748B;">WaveNxD Technical Sales • sales@wavenxd.com • www.wavenxd.com</p>
  </div>
</body>
</html>
"""

    msg = EmailMessage()
    msg["From"] = "WaveNxD Technical Sales <sales@wavenxd.com>"
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    raw_eml = msg.as_bytes()

    metadata = {
        "status": EmailDispatchStatus.PREVIEW,
        "recipient": recipient_email,
        "subject": subject,
        "quote_reference": quote_ref,
        "body_preview": plain_body[:1000],
        "notice": "Draft prepared locally. No external email was transmitted.",
        "eml_filename": f"{quote_ref}.eml",
    }
    return metadata, raw_eml


def simulate_email_delivery(
    quote_data: dict[str, Any],
    recipient_email: str,
) -> dict[str, Any]:
    """
    Simulates local email dispatch in development mode.
    Guarantees honesty: returns status 'simulated', never 'sent'.
    """
    quote_ref = quote_data.get("quote_reference", "WNXD-QUOTE")
    return {
        "status": EmailDispatchStatus.SIMULATED,
        "recipient": recipient_email,
        "quote_reference": quote_ref,
        "message": (
            f"Email delivery for quote [{quote_ref}] simulated in local test environment. "
            "No network transmission was attempted."
        ),
    }
