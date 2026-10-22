"""
Service for idempotently seeding development demo data for WaveNxD AI Sales Representative.

Seeds:
- MongoDB indexes
- Verified product catalog (12 verified ultrasonic products)
- Initial Administrator (admin@wavenxd.com)
- Customer companies (Alpha Pharma Ltd, Beta Coatings Inc)
- Customer demo users (alice@alphapharma.com, bob@betacoatings.com)
- Company-specific product assignments:
    - Alpha Pharma Ltd -> standard-nozzle-60khz
    - Beta Coatings Inc -> high-flow-conical-60khz
"""

import logging
from typing import Any

from bson import ObjectId

from app.core.security import hash_password, validate_password_strength
from app.domain.enums import UserRole
from app.models.common import utc_now
from app.models.company import Company
from app.models.user import User
from app.repositories.indexes import create_indexes
from app.services.catalog_seed import seed_catalog

logger = logging.getLogger(__name__)

# Confirmed development passwords from test fixtures and portal login
DEFAULT_DEMO_CUSTOMER_PASSWORD = "ValidCustPass123!"
DEFAULT_DEMO_ADMIN_PASSWORD = "ValidAdminPass123!"

DEMO_COMPANIES: list[dict[str, Any]] = [
    {
        "name": "Alpha Pharma Ltd",
        "contact_email": "contact@alphapharma.com",
        "notes": "Pharmaceutical and lab atomization customer",
    },
    {
        "name": "Beta Coatings Inc",
        "contact_email": "contact@betacoatings.com",
        "notes": "Industrial coatings and high-flow atomization customer",
    },
]

DEMO_USERS: list[dict[str, Any]] = [
    {
        "email": "alice@alphapharma.com",
        "full_name": "Dr. Alice",
        "role": UserRole.CUSTOMER,
        "company_name": "Alpha Pharma Ltd",
        "password": DEFAULT_DEMO_CUSTOMER_PASSWORD,
    },
    {
        "email": "bob@betacoatings.com",
        "full_name": "Bob Builder",
        "role": UserRole.CUSTOMER,
        "company_name": "Beta Coatings Inc",
        "password": DEFAULT_DEMO_CUSTOMER_PASSWORD,
    },
]

DEMO_ASSIGNMENTS: list[dict[str, str]] = [
    {
        "company_name": "Alpha Pharma Ltd",
        "catalog_key": "standard-nozzle-60khz",
    },
    {
        "company_name": "Beta Coatings Inc",
        "catalog_key": "high-flow-conical-60khz",
    },
]


async def seed_demo_data(
    database: Any,
    customer_password: str = DEFAULT_DEMO_CUSTOMER_PASSWORD,
    admin_password: str = DEFAULT_DEMO_ADMIN_PASSWORD,
) -> dict[str, Any]:
    """
    Idempotently seeds all development demo data into MongoDB.
    Safe to execute multiple times without producing duplicate records.
    """
    # 1. Ensure indexes
    logger.info("Ensuring database indexes...")
    indexes = await create_indexes(database)

    # 2. Ensure product catalog
    logger.info("Ensuring verified product catalog...")
    catalog_result = await seed_catalog(database)

    now = utc_now()

    # 3. Administrator account
    admin_email = "admin@wavenxd.com"
    existing_admin = await database.users.find_one({"email": admin_email})
    if existing_admin is None:
        admin_user = User(
            email=admin_email,
            full_name="Admin Supervisor",
            role=UserRole.ADMIN,
            company_id=None,
            password_hash=hash_password(admin_password),
            is_active=True,
            must_change_password=False,
            created_at=now,
            updated_at=now,
        )
        doc = admin_user.model_dump(by_alias=True, exclude={"id"})
        res = await database.users.insert_one(doc)
        admin_id = res.inserted_id
        admin_action = "inserted"
    else:
        admin_id = existing_admin["_id"]
        await database.users.update_one(
            {"_id": admin_id},
            {
                "$set": {
                    "full_name": "Admin Supervisor",
                    "role": UserRole.ADMIN,
                    "company_id": None,
                    "password_hash": hash_password(admin_password),
                    "is_active": True,
                    "must_change_password": False,
                    "updated_at": now,
                }
            },
        )
        admin_action = "updated"

    # 4. Companies
    company_ids: dict[str, ObjectId] = {}
    companies_summary: list[dict[str, Any]] = []

    for comp_def in DEMO_COMPANIES:
        name = comp_def["name"]
        existing = await database.companies.find_one({"name": name})
        if existing is None:
            comp = Company(
                name=name,
                contact_email=comp_def.get("contact_email"),
                notes=comp_def.get("notes"),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            doc = comp.model_dump(by_alias=True, exclude={"id"})
            res = await database.companies.insert_one(doc)
            cid = res.inserted_id
            action = "inserted"
        else:
            cid = existing["_id"]
            await database.companies.update_one(
                {"_id": cid},
                {
                    "$set": {
                        "is_active": True,
                        "contact_email": comp_def.get("contact_email"),
                        "notes": comp_def.get("notes"),
                        "updated_at": now,
                    }
                },
            )
            action = "updated"

        company_ids[name] = cid
        companies_summary.append({"name": name, "id": str(cid), "action": action})

    # 5. Customer Users
    users_summary: list[dict[str, Any]] = []

    for user_def in DEMO_USERS:
        email = user_def["email"]
        company_name = user_def["company_name"]
        cid = company_ids[company_name]
        full_name = user_def["full_name"]
        pwd = user_def.get("password", customer_password)

        existing = await database.users.find_one({"email": email})
        if existing is None:
            user = User(
                email=email,
                full_name=full_name,
                role=user_def["role"],
                company_id=cid,
                password_hash=hash_password(pwd),
                is_active=True,
                must_change_password=False,
                created_at=now,
                updated_at=now,
            )
            doc = user.model_dump(by_alias=True, exclude={"id"})
            res = await database.users.insert_one(doc)
            uid = res.inserted_id
            action = "inserted"
        else:
            uid = existing["_id"]
            await database.users.update_one(
                {"_id": uid},
                {
                    "$set": {
                        "full_name": full_name,
                        "role": user_def["role"],
                        "company_id": cid,
                        "password_hash": hash_password(pwd),
                        "is_active": True,
                        "must_change_password": False,
                        "updated_at": now,
                    }
                },
            )
            action = "updated"

        users_summary.append(
            {
                "email": email,
                "full_name": full_name,
                "role": user_def["role"].value
                if hasattr(user_def["role"], "value")
                else str(user_def["role"]),
                "company_name": company_name,
                "id": str(uid),
                "action": action,
            }
        )

    # 6. Company Product Assignments
    assignments_summary: list[dict[str, Any]] = []
    intended_products_by_company: dict[str, list[ObjectId]] = {
        name: [] for name in company_ids
    }

    for assign_def in DEMO_ASSIGNMENTS:
        company_name = assign_def["company_name"]
        catalog_key = assign_def["catalog_key"]
        cid = company_ids[company_name]

        product = await database.products.find_one({"catalog_key": catalog_key})
        if not product:
            raise RuntimeError(
                f"Required product with catalog_key '{catalog_key}' was not found in catalog."
            )

        pid = product["_id"]
        intended_products_by_company[company_name].append(pid)

        res = await database.customer_product_assignments.update_one(
            {
                "company_id": cid,
                "product_id": pid,
            },
            {
                "$set": {
                    "is_active": True,
                    "assigned_by_user_id": admin_id,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )
        action = "inserted" if res.upserted_id else "updated"

        assignments_summary.append(
            {
                "company_name": company_name,
                "catalog_key": catalog_key,
                "product_name": product.get("name"),
                "action": action,
            }
        )

    # Deactivate any unintended product assignments for demo companies to ensure isolation
    for company_name, intended_pids in intended_products_by_company.items():
        cid = company_ids[company_name]
        await database.customer_product_assignments.update_many(
            {
                "company_id": cid,
                "product_id": {"$nin": intended_pids},
                "is_active": True,
            },
            {
                "$set": {
                    "is_active": False,
                    "updated_at": now,
                }
            },
        )

    return {
        "indexes": indexes,
        "catalog": catalog_result,
        "admin": {
            "email": admin_email,
            "id": str(admin_id),
            "action": admin_action,
        },
        "companies": companies_summary,
        "users": users_summary,
        "assignments": assignments_summary,
    }


async def reset_user_password(
    database: Any,
    email: str,
    new_password: str,
) -> bool:
    """
    Safely resets a user's password in the development database.
    Enforces password strength validation and updates password_hash via Argon2id.
    """
    valid, err_msg = validate_password_strength(new_password)
    if not valid:
        raise ValueError(f"Password does not meet strength requirements: {err_msg}")

    normalized_email = email.strip().lower()
    user = await database.users.find_one({"email": normalized_email})
    if not user:
        return False

    await database.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "must_change_password": False,
                "updated_at": utc_now(),
            }
        },
    )
    return True
