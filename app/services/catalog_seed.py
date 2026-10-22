import logging
from typing import Final

from app.domain.enums import ProductStatus
from app.models.common import utc_now
from app.models.product import Product

logger = logging.getLogger(__name__)

VERIFIED_CATALOG_ITEMS: Final[list[dict]] = [
    {
        "catalog_key": "standard-nozzle-60khz",
        "name": "Standard Ultrasonic Nozzle (Torch / Conical / Flat)",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "torch / conical / flat",
        "feed_configuration": "standard",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Lab spray drying", "Spray pyrolysis"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Standard torch/conical/flat configuration; viscosity below 50 cP.",
    },
    {
        "catalog_key": "standard-nozzle-dual-feed-120khz",
        "name": "Standard Ultrasonic Nozzle with Dual-Feed Flat Oval",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "torch / conical / flat oval",
        "feed_configuration": "dual-feed flat oval",
        "frequency_khz": 120.0,
        "droplet_size_um": 25.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 3.0,
        "flow_rate_description": "3 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": [
            "Lab spray drying",
            "Spray pyrolysis",
            "Powder synthesis",
            "Hydrogen production",
        ],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Dual-feed flat oval configuration; viscosity below 50 cP.",
    },
    {
        "catalog_key": "standard-nozzle-torch-180khz",
        "name": "Standard Ultrasonic Nozzle (Torch)",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "torch",
        "feed_configuration": "standard",
        "frequency_khz": 180.0,
        "droplet_size_um": 10.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Stent coatings"],
        "status": ProductStatus.DRAFT,
        "technical_review_required": True,
        "catalog_notes": (
            "Flagged for technical review due to inconsistent frequency label "
            "in source documentation; requires technical verification before publication."
        ),
    },
    {
        "catalog_key": "high-viscosity-conical-60khz",
        "name": "High-Viscosity Conical Ultrasonic Nozzle - 60 kHz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
        "feed_configuration": None,
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 3.0,
        "flow_rate_description": "up to 3 ml/min",
        "viscosity_max_cp": 1000.0,
        "viscosity_description": "below 1000 cP",
        "applications": ["Fuel-cell coating"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Flow rate up to 3 ml/min; viscosity below 1000 cP.",
    },
    {
        "catalog_key": "high-viscosity-conical-24khz",
        "name": "High-Viscosity Conical Ultrasonic Nozzle - 24 kHz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
        "feed_configuration": None,
        "frequency_khz": 24.0,
        "droplet_size_um": 60.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 3.0,
        "flow_rate_description": "up to 3 ml/min",
        "viscosity_max_cp": 1000.0,
        "viscosity_description": "below 1000 cP",
        "applications": ["Fuel-cell coating"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Flow rate up to 3 ml/min; viscosity below 1000 cP.",
    },
    {
        "catalog_key": "high-flow-conical-60khz",
        "name": "High-Flow Conical Ultrasonic Nozzle - 60 kHz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
        "feed_configuration": None,
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 200.0,
        "flow_rate_description": "up to 200 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Industrial spray drying"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Flow rate up to 200 ml/min; viscosity below 50 cP.",
    },
    {
        "catalog_key": "pipac-conical-60khz",
        "name": "PIPAC Conical Ultrasonic Nozzle - 60 kHz",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
        "feed_configuration": None,
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 20.0,
        "flow_rate_description": "20 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "50 cP",
        "applications": ["PIPAC chemotherapy"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "PIPAC chemotherapy nozzle; viscosity 50 cP.",
    },
    {
        "catalog_key": "extended-horn-15mm-conical-60khz",
        "name": "Extended-Horn 15 mm Conical Ultrasonic Nozzle",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "conical",
        "feed_configuration": "extended-horn 15 mm",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 50.0,
        "viscosity_description": "below 50 cP",
        "applications": ["Blood-collection-tube coating"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Extended-horn 15 mm configuration; viscosity below 50 cP.",
    },
    {
        "catalog_key": "extended-horn-25mm-torch-60khz",
        "name": "Extended-Horn 25 mm Torch Ultrasonic Nozzle",
        "category": "ultrasonic_nozzle",
        "spray_pattern": "torch",
        "feed_configuration": "extended-horn 25 mm",
        "frequency_khz": 60.0,
        "droplet_size_um": 40.0,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": 5.0,
        "flow_rate_description": "5 ml/min",
        "viscosity_max_cp": 1000.0,
        "viscosity_description": "below 1000 cP",
        "applications": ["Syringe coating", "High-viscosity applications"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Extended-horn 25 mm configuration; viscosity below 1000 cP.",
    },
    {
        "catalog_key": "air-shaping-attachments",
        "name": "Air-Shaping Attachments",
        "category": "attachment",
        "spray_pattern": "focused and wide",
        "feed_configuration": None,
        "frequency_khz": None,
        "droplet_size_um": None,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": None,
        "flow_rate_description": None,
        "viscosity_max_cp": None,
        "viscosity_description": None,
        "applications": ["Spray pattern shaping"],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Air-shaping attachments providing focused and wide spray configurations.",
    },
    {
        "catalog_key": "microfluid-dispensing",
        "name": "Microfluid Dispensing System",
        "category": "dispensing_system",
        "spray_pattern": None,
        "feed_configuration": None,
        "frequency_khz": None,
        "droplet_size_um": None,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": None,
        "flow_rate_description": "metered 0–200 µl",
        "viscosity_max_cp": None,
        "viscosity_description": None,
        "applications": [
            "Blood-collection tubes",
            "Syringes",
            "Stents",
            "Balloons",
            "Catheters",
        ],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": "Metered microfluid dispensing 0–200 µl for medical and precision devices.",
    },
    {
        "catalog_key": "plc-controlled-xy-spray-pyrolysis-system",
        "name": "PLC-Controlled XY Spray-Pyrolysis System",
        "category": "spray_system",
        "spray_pattern": None,
        "feed_configuration": None,
        "frequency_khz": None,
        "droplet_size_um": None,
        "flow_rate_min_ml_min": None,
        "flow_rate_max_ml_min": None,
        "flow_rate_description": None,
        "viscosity_max_cp": None,
        "viscosity_description": None,
        "applications": [
            "Micro-coating",
            "Transparent-conductive-coating",
        ],
        "status": ProductStatus.PUBLISHED,
        "technical_review_required": False,
        "catalog_notes": (
            "PLC-controlled XY motion system with substrate heating up to 450°C "
            "and SS316 enclosure."
        ),
    },
]


def get_verified_catalog() -> list[Product]:
    """Returns the verified product catalog as validated Product instances."""
    return [Product(**item) for item in VERIFIED_CATALOG_ITEMS]


async def seed_catalog(database) -> dict[str, int]:
    """
    Seeds the verified product catalog into the database.
    This operation is idempotent: products with matching catalog_key
    are updated rather than duplicated.
    """
    catalog = get_verified_catalog()
    inserted = 0
    updated = 0

    for product in catalog:
        product_doc = product.model_dump(by_alias=True, exclude={"id"})
        catalog_key = product_doc["catalog_key"]

        existing = await database.products.find_one({"catalog_key": catalog_key})
        if existing is None:
            product_doc["created_at"] = utc_now()
            product_doc["updated_at"] = utc_now()
            await database.products.insert_one(product_doc)
            inserted += 1
        else:
            product_doc["created_at"] = existing.get("created_at", utc_now())
            product_doc["updated_at"] = utc_now()
            await database.products.replace_one(
                {"_id": existing["_id"]},
                product_doc,
            )
            updated += 1

    logger.info(
        "Seeded product catalog: %d inserted, %d updated, %d total",
        inserted,
        updated,
        len(catalog),
    )
    return {
        "inserted": inserted,
        "updated": updated,
        "total": len(catalog),
    }
