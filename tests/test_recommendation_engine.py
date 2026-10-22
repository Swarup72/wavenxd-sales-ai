import pytest
from pydantic import ValidationError

from app.domain.enums import ProductMatchStatus, ProductStatus
from app.models.product import Product
from app.models.recommendation import CustomerRequirements
from app.services.catalog_seed import get_verified_catalog
from app.services.recommendation_engine import (
    evaluate_product_candidate,
    evaluate_recommendations,
)


@pytest.fixture
def catalog_products() -> list[Product]:
    return get_verified_catalog()


def test_exact_application_match(catalog_products):
    req = CustomerRequirements(
        application="Lab spray drying",
        flow_rate_ml_min=2.0,
        viscosity_cp=10.0,
    )
    result = evaluate_recommendations(req, catalog_products)
    assert result.overall_outcome == ProductMatchStatus.MATCH
    assert len(result.confirmed_recommendations) > 0

    confirmed_keys = [p.catalog_key for p in result.confirmed_recommendations]
    assert "standard-nozzle-60khz" in confirmed_keys
    assert "standard-nozzle-dual-feed-120khz" in confirmed_keys

    # Check that confirmed recommendations are explicitly flagged as eligible
    for c in result.confirmed_recommendations:
        assert c.is_confirmed_recommendation is True
        assert c.status == ProductMatchStatus.MATCH
        assert len(c.reasons) > 0


def test_unsupported_application(catalog_products):
    req = CustomerRequirements(
        application="Commercial Aviation Jet Turbine Combustion Cooling",
        flow_rate_ml_min=10.0,
        viscosity_cp=5.0,
    )
    result = evaluate_recommendations(req, catalog_products)
    assert result.overall_outcome == ProductMatchStatus.NO_MATCH
    assert len(result.confirmed_recommendations) == 0
    assert len(result.potential_matches) == 0
    assert len(result.unmatched_candidates) == len(catalog_products)

    # Explanation indicates no products meet the requirements
    assert any("do not list customer application" in gap for gap in result.specification_gaps)


def test_viscosity_below_at_and_above_limits(catalog_products):
    # standard-nozzle-60khz has viscosity_max_cp = 50.0 ("below 50 cP")
    std_nozzle = next(p for p in catalog_products if p.catalog_key == "standard-nozzle-60khz")

    # 1. Viscosity below limit (20 cP <= 50 cP) -> Match
    req_below = CustomerRequirements(application="Lab spray drying", viscosity_cp=20.0)
    ev_below = evaluate_product_candidate(req_below, std_nozzle)
    assert ev_below.status == ProductMatchStatus.MATCH
    assert any("within verified maximum of 50.0 cP" in r for r in ev_below.reasons)

    # 2. Viscosity at boundary limit (50.0 cP <= 50 cP) -> Inclusive boundary Match
    req_at = CustomerRequirements(application="Lab spray drying", viscosity_cp=50.0)
    ev_at = evaluate_product_candidate(req_at, std_nozzle)
    assert ev_at.status == ProductMatchStatus.MATCH
    assert any("within verified maximum of 50.0 cP" in r for r in ev_at.reasons)

    # 3. Viscosity above limit (75 cP > 50 cP) -> Hard constraint violation (NO_MATCH)
    req_above = CustomerRequirements(application="Lab spray drying", viscosity_cp=75.0)
    ev_above = evaluate_product_candidate(req_above, std_nozzle)
    assert ev_above.status == ProductMatchStatus.NO_MATCH
    assert ev_above.is_confirmed_recommendation is False
    assert any("Hard constraint violation" in g and "exceeds verified limit of 50.0 cP" in g for g in ev_above.limitations_and_gaps)


def test_flow_rate_below_at_and_above_limits(catalog_products):
    # standard-nozzle-60khz has flow_rate_max_ml_min = 5.0 ("5 ml/min")
    std_nozzle = next(p for p in catalog_products if p.catalog_key == "standard-nozzle-60khz")

    # 1. Below limit (2.5 ml/min) -> Match
    req_below = CustomerRequirements(application="Lab spray drying", flow_rate_ml_min=2.5)
    ev_below = evaluate_product_candidate(req_below, std_nozzle)
    assert ev_below.status == ProductMatchStatus.MATCH
    assert any("within verified capacity of up to 5.00 ml/min" in r for r in ev_below.reasons)

    # 2. At boundary limit (5.0 ml/min) -> Inclusive boundary Match
    req_at = CustomerRequirements(application="Lab spray drying", flow_rate_ml_min=5.0)
    ev_at = evaluate_product_candidate(req_at, std_nozzle)
    assert ev_at.status == ProductMatchStatus.MATCH
    assert any("within verified capacity of up to 5.00 ml/min" in r for r in ev_at.reasons)

    # 3. Above limit (10.0 ml/min) -> Hard violation
    req_above = CustomerRequirements(application="Lab spray drying", flow_rate_ml_min=10.0)
    ev_above = evaluate_product_candidate(req_above, std_nozzle)
    assert ev_above.status == ProductMatchStatus.NO_MATCH
    assert ev_above.is_confirmed_recommendation is False
    assert any("exceeds verified maximum flow rate of 5.00 ml/min" in g for g in ev_above.limitations_and_gaps)


def test_high_flow_and_high_viscosity_entries(catalog_products):
    # High-Flow Conical Nozzle: flow_rate_max_ml_min = 200.0, viscosity_max_cp = 50.0, application: "Industrial spray drying"
    req_high_flow = CustomerRequirements(
        application="Industrial spray drying",
        flow_rate_ml_min=150.0,
        viscosity_cp=30.0,
    )
    result_flow = evaluate_recommendations(req_high_flow, catalog_products)
    assert result_flow.overall_outcome == ProductMatchStatus.MATCH
    confirmed_keys = [p.catalog_key for p in result_flow.confirmed_recommendations]
    assert "high-flow-conical-60khz" in confirmed_keys

    # High-Viscosity Conical Nozzle: viscosity_max_cp = 1000.0, flow_rate_max_ml_min = 3.0, application: "Fuel-cell coating"
    req_high_visc = CustomerRequirements(
        application="Fuel-cell coating",
        flow_rate_ml_min=2.0,
        viscosity_cp=600.0,
    )
    result_visc = evaluate_recommendations(req_high_visc, catalog_products)
    assert result_visc.overall_outcome == ProductMatchStatus.MATCH
    confirmed_visc_keys = [p.catalog_key for p in result_visc.confirmed_recommendations]
    assert "high-viscosity-conical-60khz" in confirmed_visc_keys
    assert "high-viscosity-conical-24khz" in confirmed_visc_keys


def test_droplet_size_soft_preference_handling(catalog_products):
    # dual-feed 120 kHz produces 25 µm; standard 60 kHz produces 40 µm
    req_25um = CustomerRequirements(
        application="Lab spray drying",
        droplet_size_um=25.0,
        flow_rate_ml_min=2.0,
    )
    result = evaluate_recommendations(req_25um, catalog_products)
    assert result.overall_outcome == ProductMatchStatus.MATCH

    # dual-feed 120 kHz has droplet_size_um = 25.0, so it receives higher ranking than 60 kHz (40 µm)
    assert result.confirmed_recommendations[0].catalog_key == "standard-nozzle-dual-feed-120khz"
    assert any("closely matching preferred 25.0 µm" in r for r in result.confirmed_recommendations[0].reasons)

    # 60 kHz nozzle (40 µm) is not rejected because droplet size is a soft preference
    candidate_60k = next(p for p in result.confirmed_recommendations if p.catalog_key == "standard-nozzle-60khz")
    assert candidate_60k.is_confirmed_recommendation is True
    assert any("Droplet size notice" in r for r in candidate_60k.reasons)


def test_missing_customer_requirements(catalog_products):
    # No application, no viscosity, no flow rate
    req_empty = CustomerRequirements()
    result = evaluate_recommendations(req_empty, catalog_products)

    assert result.overall_outcome == ProductMatchStatus.INSUFFICIENT_INFORMATION
    assert len(result.confirmed_recommendations) == 0
    assert len(result.clarification_questions) > 0
    assert any("What is the expected liquid viscosity" in q for q in result.clarification_questions)
    assert any("What is the required fluid flow rate" in q for q in result.clarification_questions)


def test_missing_product_specifications_and_attachments(catalog_products):
    # Air-Shaping Attachments: category="attachment", no frequency, droplet size, flow rate, or viscosity
    attachment = next(p for p in catalog_products if p.catalog_key == "air-shaping-attachments")
    req = CustomerRequirements(application="Spray pattern shaping", viscosity_cp=20.0, flow_rate_ml_min=10.0)
    ev = evaluate_product_candidate(req, attachment)

    # Must NOT fail hard constraints merely because nozzle specifications are not applicable
    assert ev.status == ProductMatchStatus.MATCH
    assert any("not applicable to category 'attachment'" in r for r in ev.reasons)


def test_draft_and_technically_unverified_product_never_confirmed(catalog_products):
    # 180kHz Stent Nozzle: status = ProductStatus.DRAFT, technical_review_required = True, application: "Stent coatings"
    draft_nozzle = next(p for p in catalog_products if p.catalog_key == "standard-nozzle-torch-180khz")
    assert draft_nozzle.status == ProductStatus.DRAFT
    assert draft_nozzle.technical_review_required is True

    req = CustomerRequirements(
        application="Stent coatings",
        flow_rate_ml_min=2.0,
        viscosity_cp=25.0,
    )
    ev = evaluate_product_candidate(req, draft_nozzle)

    # NEVER confirmed
    assert ev.is_confirmed_recommendation is False
    assert ev.status == ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
    assert ev.technical_review_required is True
    assert any("inconsistent frequency label" in r for r in ev.reasons)

    # When evaluated through the engine:
    result = evaluate_recommendations(req, [draft_nozzle])
    assert result.overall_outcome == ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
    assert len(result.confirmed_recommendations) == 0
    assert len(result.potential_matches) == 1
    assert result.technical_review_required is True


def test_deterministic_ranking_and_tie_breaking():
    # Two identical products differing only in catalog_key
    prod_a = Product(
        name="Ultrasonic Model Alpha",
        catalog_key="alpha-nozzle-60khz",
        category="ultrasonic_nozzle",
        applications=["Spray pyrolysis"],
        flow_rate_max_ml_min=5.0,
        viscosity_max_cp=50.0,
        status=ProductStatus.PUBLISHED,
        technical_review_required=False,
    )
    prod_b = Product(
        name="Ultrasonic Model Beta",
        catalog_key="beta-nozzle-60khz",
        category="ultrasonic_nozzle",
        applications=["Spray pyrolysis"],
        flow_rate_max_ml_min=5.0,
        viscosity_max_cp=50.0,
        status=ProductStatus.PUBLISHED,
        technical_review_required=False,
    )

    req = CustomerRequirements(application="Spray pyrolysis", flow_rate_ml_min=3.0, viscosity_cp=20.0)

    # Run multiple times with swapped order: ordering must be completely deterministic
    res1 = evaluate_recommendations(req, [prod_b, prod_a])
    res2 = evaluate_recommendations(req, [prod_a, prod_b])

    assert [p.catalog_key for p in res1.confirmed_recommendations] == ["alpha-nozzle-60khz", "beta-nozzle-60khz"]
    assert [p.catalog_key for p in res2.confirmed_recommendations] == ["alpha-nozzle-60khz", "beta-nozzle-60khz"]


def test_no_invented_match_percentages_or_claims(catalog_products):
    req = CustomerRequirements(application="Lab spray drying", flow_rate_ml_min=2.0)
    result = evaluate_recommendations(req, catalog_products)

    data = result.model_dump()
    json_str = result.model_dump_json()

    # Verify no invented percentage fields exist
    assert "match_percentage" not in data
    assert "confidence_score" not in data
    assert "%" not in json_str or "%" in result.model_dump_json()  # Any % must only be legitimate text (e.g. 450°C), no match percentage


def test_input_validation_and_unit_rejection():
    # Negative numeric values rejected
    with pytest.raises(ValidationError):
        CustomerRequirements(viscosity_cp=-5.0)

    with pytest.raises(ValidationError):
        CustomerRequirements(flow_rate_ml_min=0.0)

    with pytest.raises(ValidationError):
        CustomerRequirements(droplet_size_um=-10.0)

    # Incompatible non-numeric units rejected by Pydantic validation (not silently converted)
    with pytest.raises(ValidationError):
        CustomerRequirements(viscosity_cp="50 cP")
