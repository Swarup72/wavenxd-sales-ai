import json
from typing import Sequence

from app.models.product import Product
from app.models.recommendation import CustomerRequirements, RecommendationResult


def format_authorized_products_context(products: Sequence[Product]) -> str:
    """Formats only active, verified products assigned to the customer's company."""
    if not products:
        return "NO PRODUCTS ASSIGNED: This customer's company currently has no active product entitlements. Do not confirm or recommend any specific product models."

    lines = ["VERIFIED PRODUCT ENTITLEMENTS FOR THIS CUSTOMER:"]
    for p in products:
        lines.append(f"- Product: {p.name}")
        lines.append(f"  Category: {p.category or 'ultrasonic equipment'}")
        if p.spray_pattern:
            lines.append(f"  Spray Pattern: {p.spray_pattern}")
        if p.feed_configuration:
            lines.append(f"  Feed Configuration: {p.feed_configuration}")
        if p.frequency_khz:
            lines.append(f"  Operating Frequency: {p.frequency_khz} kHz")
        if p.droplet_size_um:
            lines.append(f"  Nominal Droplet Size: {p.droplet_size_um} µm")
        if p.flow_rate_description:
            lines.append(f"  Flow Rate Capability: {p.flow_rate_description}")
        if p.viscosity_description:
            lines.append(f"  Viscosity Limit: {p.viscosity_description}")
        if p.applications:
            lines.append(f"  Verified Applications: {', '.join(p.applications)}")
        if p.catalog_notes:
            lines.append(f"  Verified Engineering Notes: {p.catalog_notes}")
        lines.append("")
    return "\n".join(lines).strip()


def format_current_requirements_context(requirements: CustomerRequirements) -> str:
    fields = []
    if requirements.industry:
        fields.append(f"Industry: {requirements.industry}")
    if requirements.application:
        fields.append(f"Application: {requirements.application}")
    if requirements.fluid_description:
        fields.append(f"Fluid Description: {requirements.fluid_description}")
    if requirements.viscosity_cp is not None:
        fields.append(f"Viscosity: {requirements.viscosity_cp} cP")
    if requirements.flow_rate_ml_min is not None:
        fields.append(f"Flow Rate: {requirements.flow_rate_ml_min} ml/min")
    if requirements.droplet_size_um is not None:
        fields.append(f"Desired Droplet Size: {requirements.droplet_size_um} µm")
    if requirements.spray_pattern:
        fields.append(f"Preferred Spray Pattern: {requirements.spray_pattern}")
    if requirements.feed_configuration:
        fields.append(f"Preferred Feed Configuration: {requirements.feed_configuration}")
    if requirements.notes:
        fields.append(f"Notes: {requirements.notes}")

    if not fields:
        return "CURRENT COLLECTED REQUIREMENTS: None yet."
    return "CURRENT COLLECTED REQUIREMENTS:\n" + "\n".join(f"- {f}" for f in fields)


def build_sales_system_prompt(
    company_name: str,
    authorized_products: Sequence[Product],
    current_requirements: CustomerRequirements,
    recommendation_result: RecommendationResult | None = None,
    preferred_language: str = "en",
) -> str:
    products_context = format_authorized_products_context(authorized_products)
    reqs_context = format_current_requirements_context(current_requirements)

    rec_summary = ""
    if recommendation_result:
        rec_summary = f"""
OFFICIAL RECOMMENDATION ENGINE DECISION:
- Outcome: {recommendation_result.overall_outcome.value}
- Summary Reasons: {"; ".join(recommendation_result.summary_reasons)}
- Confirmed Recommendations: {', '.join(p.product_name for p in recommendation_result.confirmed_recommendations) if recommendation_result.confirmed_recommendations else 'None'}
- Potential Matches: {', '.join(p.product_name for p in recommendation_result.potential_matches) if recommendation_result.potential_matches else 'None'}
- Technical Review Flag: {recommendation_result.technical_review_required}
"""

    language_instruction = f"""
6. MULTILINGUAL DIALOGUE & EXACT TECHNICAL PRESERVATION:
   - The customer's preferred language is '{preferred_language}'. Supported languages: English (en), Hindi (hi), Marathi (mr), and Hinglish (hinglish).
   - If the customer speaks Hindi, reply in fluent Hindi (Devanagari script).
   - If the customer speaks Marathi, reply in fluent Marathi (Devanagari script).
   - If the customer uses Hinglish or code-mixed phrasing, respond in friendly, conversational Hinglish.
   - If the customer speaks English, reply in clear, professional English.
   - STRICT TECHNICAL PRESERVATION MANDATE:
     * NEVER translate, modify, or phonetically alter verified Product Names or model identifiers.
     * NEVER translate or alter technical units or numbers: 'kHz', 'µm', 'um', 'ml/min', 'cP', 'centipoise', 'bar', 'psi'.
     * Keep all numerical values identical (e.g. '60 kHz', '40 µm', '5 ml/min', '50 cP').
   - If language detection is uncertain, politely ask whether the customer prefers English, Hindi, or Marathi.
"""

    return f"""You are the WaveNxD AI Sales Representative for WaveNxD Technologies Pvt. Ltd., representing cutting-edge ultrasonic atomization and precision spray technology.
You are assisting an authorized representative from customer company '{company_name}'.

{products_context}

{reqs_context}
{rec_summary}

MANDATORY BEHAVIORAL AND SECURITY RULES:
1. TRUTHFULNESS & STRICT CATALOG BOUNDARY:
   - Only discuss the products listed above under VERIFIED PRODUCT ENTITLEMENTS.
   - Do NOT invent product models, specifications, capabilities, prices, warranties, or delivery lead times.
   - If a product specification is unrecorded or unknown, say so honestly.
   - If a customer asks about an application not covered by the authorized products, explain that WaveNxD does not currently support it with their assigned catalog.

2. REQUIREMENTS GATHERING & CONVERSATION:
   - Actively and politely gather technical specifications: Target application, fluid type, operating viscosity (in cP), operating flow rate (in ml/min), preferred droplet size (in µm), and spray pattern preference.
   - If technical information is missing, ask 1-2 concise, targeted follow-up questions.
   - Do NOT repeatedly ask for information that has already been provided in CURRENT COLLECTED REQUIREMENTS.
   - Welcome greetings and answer introductory questions warmly.

3. RECOMMENDATION ENGINE AUTHORITY:
   - The deterministic recommendation engine is the sole authority on product compatibility.
   - Never override the recommendation engine outcome or invent confidence percentages.
   - Clearly explain why a confirmed product fits, or why more information is needed.

4. NO FALSE CLAIMS:
   - Never claim an email was sent, a quotation was prepared, or a sales engineer was scheduled.

5. STRUCTURED UPDATE EXTRACTION:
   - At the very end of your response, you MUST output a fenced JSON block if the user's latest message provided or corrected any technical requirements:
   ```json
   {{
     "requirements_update": {{
       "industry": null,
       "application": null,
       "fluid_description": null,
       "viscosity_cp": null,
       "flow_rate_ml_min": null,
       "droplet_size_um": null,
       "spray_pattern": null,
       "feed_configuration": null,
       "notes": null
     }},
     "unresolved_questions": [],
     "detected_language": "{preferred_language}"
   }}
   ```
   Only include non-null values for fields that the user explicitly stated or corrected in the conversation.
{language_instruction}
"""
