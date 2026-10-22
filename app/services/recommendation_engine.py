import re
from typing import Sequence

from app.domain.enums import ProductMatchStatus, ProductStatus
from app.models.product import Product
from app.models.recommendation import (
    CandidateEvaluation,
    CustomerRequirements,
    RecommendationResult,
)

NON_NOZZLE_CATEGORIES = frozenset({"attachment", "dispensing_system", "spray_system"})


def _normalize_tokens(text: str | None) -> set[str]:
    """Extracts lowercase alphanumeric tokens for normalized application matching."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = {t for t in cleaned.split() if len(t) > 2}
    return tokens


def _matches_application(req_app: str | None, product_apps: list[str]) -> tuple[bool, bool]:
    """
    Evaluates whether the customer's application matches any product application.
    Returns (is_match, is_exact_or_strong).
    """
    if not req_app:
        return False, False

    req_lower = req_app.strip().lower()
    req_tokens = _normalize_tokens(req_app)

    # 1. Exact string match against one of the applications
    for app in product_apps:
        app_lower = app.lower()
        if req_lower == app_lower:
            return True, True
        if req_lower in app_lower or app_lower in req_lower:
            return True, True

    # 2. Token overlap matching (e.g. "spray drying" matches "Lab spray drying" or "Industrial spray drying")
    for app in product_apps:
        app_tokens = _normalize_tokens(app)
        overlap = req_tokens & app_tokens
        if len(overlap) >= 2 or (len(req_tokens) == 1 and len(overlap) == 1):
            return True, True

    # 3. Specific domain synonym/keyword rules:
    # Stents / stent coating
    if "stent" in req_lower and any("stent" in a.lower() for a in product_apps):
        return True, True
    # Pyrolysis / spray pyrolysis
    if "pyrolysis" in req_lower and any("pyrolysis" in a.lower() for a in product_apps):
        return True, True
    # Fuel cell / fuel-cell
    if "fuel" in req_lower and any("fuel" in a.lower() for a in product_apps):
        return True, True
    # Blood collection tube / blood tube
    if "blood" in req_lower and any("blood" in a.lower() for a in product_apps):
        return True, True
    # Syringe
    if "syringe" in req_lower and any("syringe" in a.lower() for a in product_apps):
        return True, True
    # Chemotherapy / PIPAC
    if ("chemo" in req_lower or "pipac" in req_lower) and any("pipac" in a.lower() or "chemo" in a.lower() for a in product_apps):
        return True, True

    return False, False


def evaluate_product_candidate(
    requirements: CustomerRequirements,
    product: Product,
) -> CandidateEvaluation:
    """
    Evaluates a single candidate product deterministically against customer requirements.
    Adheres strictly to verified specifications without inventing capabilities.
    """
    reasons: list[str] = []
    limitations_and_gaps: list[str] = []
    clarifications_required: list[str] = []
    ranking_score = 0
    is_hard_violation = False
    is_draft_or_review = product.status == ProductStatus.DRAFT or product.technical_review_required
    is_non_nozzle = product.category in NON_NOZZLE_CATEGORIES

    # --- 1. Draft and Technical Review Guard ---
    if is_draft_or_review:
        reasons.append(
            f"Product '{product.name}' is currently in {product.status.value.upper()} status "
            "and flagged for technical review (inconsistent frequency label in source documentation); "
            "cannot be confirmed as an ordinary recommendation without technical verification."
        )
        ranking_score -= 10

    # --- 2. Application Suitability ---
    if requirements.application:
        is_app_match, is_strong = _matches_application(requirements.application, product.applications)
        if is_app_match:
            reasons.append(
                f"Application match: Verified for '{', '.join(product.applications)}' "
                f"which aligns with requested application '{requirements.application}'."
            )
            ranking_score += 10 if is_strong else 5
        else:
            limitations_and_gaps.append(
                f"Documented applications ({', '.join(product.applications) if product.applications else 'None listed'}) "
                f"do not list customer application '{requirements.application}'."
            )
            is_hard_violation = True
    else:
        clarifications_required.append(
            "Customer application not specified; please specify target application to confirm product suitability."
        )
        limitations_and_gaps.append("Target application is unknown.")

    # --- 3. Viscosity Compatibility ---
    if requirements.viscosity_cp is not None:
        if product.viscosity_max_cp is not None:
            # Inclusive boundary: viscosity_cp <= product.viscosity_max_cp is compatible
            if requirements.viscosity_cp <= product.viscosity_max_cp:
                reasons.append(
                    f"Viscosity compatible: Operating viscosity of {requirements.viscosity_cp:.1f} cP is within "
                    f"verified maximum of {product.viscosity_max_cp:.1f} cP ('{product.viscosity_description}')."
                )
                ranking_score += 3
            else:
                limitations_and_gaps.append(
                    f"Hard constraint violation: Required viscosity {requirements.viscosity_cp:.1f} cP exceeds "
                    f"verified limit of {product.viscosity_max_cp:.1f} cP ('{product.viscosity_description}')."
                )
                is_hard_violation = True
        else:
            if is_non_nozzle:
                reasons.append(
                    f"Viscosity specification not applicable to category '{product.category}'."
                )
            else:
                limitations_and_gaps.append(
                    "Product viscosity limit is not recorded in catalog; requires technical review."
                )
                clarifications_required.append(
                    f"Confirm if fluid viscosity of {requirements.viscosity_cp:.1f} cP is supported by engineering."
                )
    else:
        if product.viscosity_max_cp is not None:
            limitations_and_gaps.append(
                f"Customer fluid viscosity unknown; product verified for '{product.viscosity_description}'."
            )
            clarifications_required.append(
                "What is the expected liquid viscosity in cP at operating temperature?"
            )

    # --- 4. Flow Rate Compatibility ---
    if requirements.flow_rate_ml_min is not None:
        if product.flow_rate_max_ml_min is not None:
            # Inclusive boundary: flow_rate_ml_min <= product.flow_rate_max_ml_min is compatible
            if requirements.flow_rate_ml_min <= product.flow_rate_max_ml_min:
                reasons.append(
                    f"Flow rate compatible: Required flow rate of {requirements.flow_rate_ml_min:.2f} ml/min is "
                    f"within verified capacity of up to {product.flow_rate_max_ml_min:.2f} ml/min "
                    f"('{product.flow_rate_description}')."
                )
                ranking_score += 3
            else:
                limitations_and_gaps.append(
                    f"Hard constraint violation: Required flow rate {requirements.flow_rate_ml_min:.2f} ml/min exceeds "
                    f"verified maximum flow rate of {product.flow_rate_max_ml_min:.2f} ml/min "
                    f"('{product.flow_rate_description}')."
                )
                is_hard_violation = True

            if product.flow_rate_min_ml_min is not None and requirements.flow_rate_ml_min < product.flow_rate_min_ml_min:
                limitations_and_gaps.append(
                    f"Required flow rate {requirements.flow_rate_ml_min:.2f} ml/min is below minimum verified "
                    f"operating flow rate of {product.flow_rate_min_ml_min:.2f} ml/min."
                )
                is_hard_violation = True
        else:
            if product.flow_rate_description:
                reasons.append(
                    f"Product specifies flow capability as: '{product.flow_rate_description}'."
                )
                if "metered" in product.flow_rate_description.lower():
                    clarifications_required.append(
                        f"Product utilizes metered dispensing ('{product.flow_rate_description}'); verify whether "
                        f"continuous flow rate of {requirements.flow_rate_ml_min:.2f} ml/min matches metered delivery."
                    )
            elif is_non_nozzle:
                reasons.append(
                    f"Flow rate specification is not applicable to category '{product.category}'."
                )
            else:
                limitations_and_gaps.append("Product flow rate specification is not recorded in catalog.")
    else:
        if product.flow_rate_description:
            limitations_and_gaps.append(
                f"Customer flow rate unknown; product capability is '{product.flow_rate_description}'."
            )
            clarifications_required.append(
                "What is the required fluid flow rate in ml/min?"
            )

    # --- 5. Droplet Size (Soft Preference) ---
    if requirements.droplet_size_um is not None:
        if product.droplet_size_um is not None:
            delta = abs(product.droplet_size_um - requirements.droplet_size_um)
            if delta <= 5.0:
                reasons.append(
                    f"Droplet size aligned: Nominal droplet size is {product.droplet_size_um:.1f} µm, "
                    f"closely matching preferred {requirements.droplet_size_um:.1f} µm."
                )
                ranking_score += 2
            else:
                reasons.append(
                    f"Droplet size notice: Nominal droplet size is {product.droplet_size_um:.1f} µm "
                    f"(at {product.frequency_khz} kHz), compared to preferred {requirements.droplet_size_um:.1f} µm. "
                    "Droplet size is inversely related to ultrasonic frequency."
                )
        else:
            if not is_non_nozzle:
                limitations_and_gaps.append("Droplet size specification is not recorded for this nozzle.")
    else:
        if product.droplet_size_um is not None:
            reasons.append(
                f"Nominal droplet size is {product.droplet_size_um:.1f} µm at {product.frequency_khz} kHz."
            )

    # --- 6. Spray Pattern Preference ---
    if requirements.spray_pattern and product.spray_pattern:
        req_pattern = requirements.spray_pattern.lower()
        prod_pattern = product.spray_pattern.lower()
        if req_pattern in prod_pattern:
            reasons.append(
                f"Spray pattern matches preference: '{product.spray_pattern}' supports '{requirements.spray_pattern}'."
            )
            ranking_score += 2
        else:
            limitations_and_gaps.append(
                f"Spray pattern preference '{requirements.spray_pattern}' differs from verified pattern '{product.spray_pattern}'."
            )

    # --- 7. Feed Configuration Preference ---
    if requirements.feed_configuration and product.feed_configuration:
        req_feed = requirements.feed_configuration.lower()
        prod_feed = product.feed_configuration.lower()
        if req_feed in prod_feed:
            reasons.append(
                f"Feed configuration matches preference: '{product.feed_configuration}'."
            )
            ranking_score += 2
        else:
            limitations_and_gaps.append(
                f"Feed configuration preference '{requirements.feed_configuration}' differs from '{product.feed_configuration}'."
            )

    # --- Categorical Status Determination ---
    if not requirements.application and requirements.viscosity_cp is None and requirements.flow_rate_ml_min is None:
        match_status = ProductMatchStatus.INSUFFICIENT_INFORMATION
        is_confirmed = False
    elif is_hard_violation:
        match_status = ProductMatchStatus.NO_MATCH
        is_confirmed = False
    elif is_draft_or_review:
        match_status = ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
        is_confirmed = False
    elif not requirements.application:
        match_status = ProductMatchStatus.INSUFFICIENT_INFORMATION
        is_confirmed = False
    elif any("requires technical review" in g.lower() or "metered" in g.lower() for g in limitations_and_gaps):
        match_status = ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
        is_confirmed = False
    else:
        match_status = ProductMatchStatus.MATCH
        is_confirmed = True

    return CandidateEvaluation(
        product_id=str(product.id) if product.id else (product.catalog_key or ""),
        catalog_key=product.catalog_key,
        product_name=product.name,
        category=product.category,
        status=match_status,
        is_confirmed_recommendation=is_confirmed,
        technical_review_required=is_draft_or_review,
        reasons=reasons,
        limitations_and_gaps=limitations_and_gaps,
        clarifications_required=clarifications_required,
        ranking_score=ranking_score,
    )


def evaluate_recommendations(
    requirements: CustomerRequirements,
    candidate_products: Sequence[Product],
) -> RecommendationResult:
    """
    Pure, deterministic recommendation and ranking engine.
    Given customer requirements and an authorized set of candidate products:
    1. Evaluates each candidate against deterministic compatibility rules.
    2. Ranks candidates passing hard constraints by relevance and compatibility signals.
    3. Breaks ties deterministically by catalog_key / product name.
    4. Explains each ranking and aggregates clarification questions.
    """
    evaluations: list[CandidateEvaluation] = []
    all_clarifications: list[str] = []
    all_gaps: list[str] = []

    # If customer provided unresolved questions, carry them into clarifications
    for q in requirements.unresolved_questions:
        all_clarifications.append(f"Customer question: {q}")

    for prod in candidate_products:
        ev = evaluate_product_candidate(requirements, prod)
        evaluations.append(ev)
        for c in ev.clarifications_required:
            if c not in all_clarifications:
                all_clarifications.append(c)
        for g in ev.limitations_and_gaps:
            if g not in all_gaps:
                all_gaps.append(g)

    confirmed: list[CandidateEvaluation] = []
    potential: list[CandidateEvaluation] = []
    insufficient: list[CandidateEvaluation] = []
    unmatched: list[CandidateEvaluation] = []

    for ev in evaluations:
        if ev.status == ProductMatchStatus.MATCH:
            confirmed.append(ev)
        elif ev.status == ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION:
            potential.append(ev)
        elif ev.status == ProductMatchStatus.INSUFFICIENT_INFORMATION:
            insufficient.append(ev)
        else:
            unmatched.append(ev)

    # Deterministic sorting function:
    # 1. ranking_score descending
    # 2. catalog_key ascending
    # 3. product_name ascending
    sort_key = lambda e: (-e.ranking_score, e.catalog_key or "", e.product_name)
    confirmed.sort(key=sort_key)
    potential.sort(key=sort_key)
    insufficient.sort(key=sort_key)
    unmatched.sort(key=sort_key)

    # Assign explainable ranking descriptions
    for idx, e in enumerate(confirmed, start=1):
        e.ranking_explanation = (
            f"Ranked #{idx} confirmed recommendation: passes all operating constraints with "
            f"ranking score {e.ranking_score}."
        )

    for idx, e in enumerate(potential, start=1):
        reasons_summary = "; ".join(e.limitations_and_gaps[:2]) if e.limitations_and_gaps else "Requires clarification"
        e.ranking_explanation = (
            f"Ranked #{idx} potential match: {reasons_summary}."
        )

    for idx, e in enumerate(insufficient, start=1):
        e.ranking_explanation = (
            f"Candidate #{idx}: Insufficient customer requirements provided to confirm match."
        )

    for e in unmatched:
        violation_summary = "; ".join(e.limitations_and_gaps[:2]) if e.limitations_and_gaps else "Does not meet application requirements"
        e.ranking_explanation = f"Not recommended: {violation_summary}."

    # Determine overall outcome
    summary_reasons: list[str] = []
    if not candidate_products:
        overall_outcome = ProductMatchStatus.INSUFFICIENT_INFORMATION
        summary_reasons.append(
            "No active product entitlements are currently assigned to your company. "
            "Please request access to catalog products before running recommendations."
        )
    elif not requirements.application and requirements.viscosity_cp is None and requirements.flow_rate_ml_min is None:
        overall_outcome = ProductMatchStatus.INSUFFICIENT_INFORMATION
        summary_reasons.append(
            "Insufficient technical requirements provided. Please provide application, operating viscosity, or required flow rate."
        )
    elif confirmed:
        overall_outcome = ProductMatchStatus.MATCH
        summary_reasons.append(
            f"Found {len(confirmed)} confirmed recommendation(s) matching your verified requirements."
        )
    elif potential:
        overall_outcome = ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
        summary_reasons.append(
            f"Found {len(potential)} potential candidate(s) requiring confirmation or technical review."
        )
    elif insufficient:
        overall_outcome = ProductMatchStatus.INSUFFICIENT_INFORMATION
        summary_reasons.append(
            "Insufficient technical requirements provided. Please specify target application, operating viscosity, or required flow rate."
        )
    else:
        overall_outcome = ProductMatchStatus.NO_MATCH
        summary_reasons.append(
            "None of your company's assigned catalog products meet the specified application and operational requirements."
        )

    any_tech_review = any(e.technical_review_required for e in confirmed + potential + insufficient)

    return RecommendationResult(
        overall_outcome=overall_outcome,
        candidate_evaluations=confirmed + potential + insufficient + unmatched,
        confirmed_recommendations=confirmed,
        potential_matches=potential + insufficient,
        unmatched_candidates=unmatched,
        summary_reasons=summary_reasons,
        specification_gaps=all_gaps,
        clarification_questions=all_clarifications,
        technical_review_required=any_tech_review,
    )
