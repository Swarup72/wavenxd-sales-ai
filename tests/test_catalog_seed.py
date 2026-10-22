import re

import pytest

from app.domain.enums import ProductStatus
from app.services.catalog_seed import (
    VERIFIED_CATALOG_ITEMS,
    get_verified_catalog,
    seed_catalog,
)


def test_exact_catalog_entry_count():
    """Verify that exactly 12 verified products are defined."""
    assert len(VERIFIED_CATALOG_ITEMS) == 12
    catalog = get_verified_catalog()
    assert len(catalog) == 12


def test_no_fabricated_model_numbers():
    """
    Verify that neither catalog keys nor product names invent fictitious model IDs
    (such as 'WNX-180', 'MODEL-12', 'NOZ-60T', 'V1.0', etc.).
    """
    # Pattern matching typical fabricated model codes (e.g. 2-4 uppercase letters followed by digits)
    fabricated_model_pattern = re.compile(r"\b[A-Z]{2,5}-\d{2,4}[A-Z]?\b")

    for product in get_verified_catalog():
        assert not fabricated_model_pattern.search(product.name), (
            f"Product name '{product.name}' contains what appears to be a fabricated model number"
        )
        assert product.catalog_key is not None
        # Catalog key must follow lowercase hyphenated slug convention
        assert re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", product.catalog_key)
        assert not fabricated_model_pattern.search(product.catalog_key.upper())


def test_technical_review_flag_for_180khz_stent():
    """
    The 180 kHz stent-coating row must be flagged for technical review
    and kept in DRAFT status due to inconsistent frequency label in source.
    """
    catalog = get_verified_catalog()
    stent_items = [
        p for p in catalog if "Stent coatings" in p.applications or p.frequency_khz == 180.0
    ]
    assert len(stent_items) == 1
    stent_item = stent_items[0]

    assert stent_item.frequency_khz == 180.0
    assert stent_item.technical_review_required is True
    assert stent_item.status == ProductStatus.DRAFT
    assert stent_item.catalog_notes is not None
    assert "technical review" in stent_item.catalog_notes.lower()


def test_correct_product_publication_status():
    """
    Exactly 11 verified products should be PUBLISHED, and the 1 flagged
    product (180 kHz stent) should be DRAFT. No products should be ARCHIVED.
    """
    catalog = get_verified_catalog()
    published = [p for p in catalog if p.status == ProductStatus.PUBLISHED]
    drafts = [p for p in catalog if p.status == ProductStatus.DRAFT]
    archived = [p for p in catalog if p.status == ProductStatus.ARCHIVED]

    assert len(published) == 11
    assert len(drafts) == 1
    assert len(archived) == 0

    assert drafts[0].catalog_key == "standard-nozzle-torch-180khz"
    assert drafts[0].technical_review_required is True


def test_unknown_specifications_remain_none():
    """
    Attachments and systems without ultrasonic frequency or droplet size must
    keep those fields as None. Flow rate min ml/min must also remain None when unspecified.
    """
    catalog = {p.catalog_key: p for p in get_verified_catalog()}

    # Air-shaping attachment: no ultrasonic frequency, no droplet size, no flow rate, no viscosity
    air_shaping = catalog["air-shaping-attachments"]
    assert air_shaping.frequency_khz is None
    assert air_shaping.droplet_size_um is None
    assert air_shaping.flow_rate_min_ml_min is None
    assert air_shaping.flow_rate_max_ml_min is None
    assert air_shaping.viscosity_max_cp is None

    # Microfluid dispensing system: dispensing volume not ultrasonic frequency
    dispensing = catalog["microfluid-dispensing"]
    assert dispensing.frequency_khz is None
    assert dispensing.droplet_size_um is None
    assert dispensing.viscosity_max_cp is None

    # PLC spray pyrolysis system: motion/substrate system
    pyrolysis = catalog["plc-controlled-xy-spray-pyrolysis-system"]
    assert pyrolysis.frequency_khz is None
    assert pyrolysis.droplet_size_um is None
    assert pyrolysis.viscosity_max_cp is None


def test_flow_rate_and_viscosity_wording_preserved():
    """
    Verify descriptions such as 'up to 200 ml/min', 'up to 3 ml/min', 'metered 0–200 µl',
    and 'below 1000 cP' are preserved where numeric values alone could be ambiguous.
    """
    catalog = {p.catalog_key: p for p in get_verified_catalog()}

    # High-viscosity 60 kHz
    hv60 = catalog["high-viscosity-conical-60khz"]
    assert hv60.flow_rate_description == "up to 3 ml/min"
    assert hv60.viscosity_description == "below 1000 cP"
    assert hv60.flow_rate_max_ml_min == 3.0
    assert hv60.viscosity_max_cp == 1000.0

    # High-viscosity 24 kHz
    hv24 = catalog["high-viscosity-conical-24khz"]
    assert hv24.flow_rate_description == "up to 3 ml/min"
    assert hv24.viscosity_description == "below 1000 cP"
    assert hv24.flow_rate_max_ml_min == 3.0
    assert hv24.viscosity_max_cp == 1000.0

    # High-flow conical
    high_flow = catalog["high-flow-conical-60khz"]
    assert high_flow.flow_rate_description == "up to 200 ml/min"
    assert high_flow.viscosity_description == "below 50 cP"
    assert high_flow.flow_rate_max_ml_min == 200.0
    assert high_flow.viscosity_max_cp == 50.0

    # Microfluid dispensing
    dispensing = catalog["microfluid-dispensing"]
    assert dispensing.flow_rate_description == "metered 0–200 µl"

    # PIPAC
    pipac = catalog["pipac-conical-60khz"]
    assert pipac.flow_rate_description == "20 ml/min"
    assert pipac.viscosity_description == "50 cP"
    assert pipac.flow_rate_max_ml_min == 20.0
    assert pipac.viscosity_max_cp == 50.0


class MockProductCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.id_counter = 1

    async def find_one(self, filter_dict):
        key = filter_dict.get("catalog_key")
        return self.docs.get(key)

    async def insert_one(self, doc):
        doc_copy = dict(doc)
        doc_copy["_id"] = str(self.id_counter)
        self.id_counter += 1
        self.docs[doc["catalog_key"]] = doc_copy
        return doc_copy

    async def replace_one(self, filter_dict, doc):
        # find matching doc
        for k, existing in self.docs.items():
            if existing["_id"] == filter_dict.get("_id"):
                doc_copy = dict(doc)
                doc_copy["_id"] = existing["_id"]
                self.docs[k] = doc_copy
                return


class MockDatabaseForSeed:
    def __init__(self):
        self.products = MockProductCollection()


@pytest.mark.anyio
async def test_catalog_seed_idempotency():
    """
    Rerunning seed_catalog must not create duplicate products in the database.
    First run inserts 12; second run updates 12; total products remains 12.
    """
    db = MockDatabaseForSeed()

    # First run
    res1 = await seed_catalog(db)
    assert res1["inserted"] == 12
    assert res1["updated"] == 0
    assert res1["total"] == 12
    assert len(db.products.docs) == 12

    # Second run (idempotent)
    res2 = await seed_catalog(db)
    assert res2["inserted"] == 0
    assert res2["updated"] == 12
    assert res2["total"] == 12
    assert len(db.products.docs) == 12

    # Third run (still idempotent)
    res3 = await seed_catalog(db)
    assert res3["inserted"] == 0
    assert res3["updated"] == 12
    assert res3["total"] == 12
    assert len(db.products.docs) == 12
