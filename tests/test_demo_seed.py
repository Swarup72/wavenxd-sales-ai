import pytest
from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.core.security import hash_password, validate_password_strength, verify_password
from app.services.demo_seed import (
    DEFAULT_DEMO_ADMIN_PASSWORD,
    DEFAULT_DEMO_CUSTOMER_PASSWORD,
    reset_user_password,
    seed_demo_data,
)


def test_demo_passwords_meet_strength_criteria():
    """Confirms documented demo passwords meet project password strength rules."""
    valid, msg = validate_password_strength(DEFAULT_DEMO_CUSTOMER_PASSWORD)
    assert valid is True
    assert msg is None

    valid, msg = validate_password_strength(DEFAULT_DEMO_ADMIN_PASSWORD)
    assert valid is True
    assert msg is None

    # Verify Argon2id verification
    hashed = hash_password(DEFAULT_DEMO_CUSTOMER_PASSWORD)
    assert verify_password(DEFAULT_DEMO_CUSTOMER_PASSWORD, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


@pytest.mark.anyio
async def test_reset_user_password_validation():
    """Confirms password reset enforces password length and character requirements."""
    class DummyDB:
        pass

    with pytest.raises(ValueError, match="Password must be at least 8 characters"):
        await reset_user_password(DummyDB(), "alice@alphapharma.com", "short")


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_mongodb_seed_demo_data_idempotency():
    """
    Verifies that seed_demo_data creates the correct structure on MongoDB
    and is strictly idempotent across repeated executions.
    """
    settings = get_settings()
    test_db_name = f"{settings.mongodb_database}_demo_seed_test"
    client = AsyncMongoClient(settings.mongodb_uri)

    try:
        await client.admin.command("ping")
        db = client[test_db_name]

        # Clean collection for test run
        await client.drop_database(test_db_name)

        # 1. First execution
        res1 = await seed_demo_data(db)
        assert res1["admin"]["action"] == "inserted"
        assert len(res1["companies"]) == 2
        assert len(res1["users"]) == 2
        assert len(res1["assignments"]) == 2

        assert await db.users.count_documents({}) == 3  # 1 admin + 2 customers
        assert await db.companies.count_documents({}) == 2
        assert await db.products.count_documents({}) == 12
        assert await db.customer_product_assignments.count_documents({"is_active": True}) == 2

        # Verify Alice's company and assigned product
        alice = await db.users.find_one({"email": "alice@alphapharma.com"})
        assert alice is not None
        assert alice["role"] == "customer"
        assert alice["must_change_password"] is False
        assert verify_password(DEFAULT_DEMO_CUSTOMER_PASSWORD, alice["password_hash"]) is True

        alpha_pharma = await db.companies.find_one({"name": "Alpha Pharma Ltd"})
        assert alpha_pharma is not None
        assert alice["company_id"] == alpha_pharma["_id"]

        std_nozzle = await db.products.find_one({"catalog_key": "standard-nozzle-60khz"})
        alice_assignment = await db.customer_product_assignments.find_one(
            {"company_id": alpha_pharma["_id"], "product_id": std_nozzle["_id"], "is_active": True}
        )
        assert alice_assignment is not None

        # Verify Bob's company and assigned product
        bob = await db.users.find_one({"email": "bob@betacoatings.com"})
        assert bob is not None
        assert bob["role"] == "customer"
        assert bob["must_change_password"] is False
        assert verify_password(DEFAULT_DEMO_CUSTOMER_PASSWORD, bob["password_hash"]) is True

        beta_coatings = await db.companies.find_one({"name": "Beta Coatings Inc"})
        assert beta_coatings is not None
        assert bob["company_id"] == beta_coatings["_id"]

        high_flow = await db.products.find_one({"catalog_key": "high-flow-conical-60khz"})
        bob_assignment = await db.customer_product_assignments.find_one(
            {"company_id": beta_coatings["_id"], "product_id": high_flow["_id"], "is_active": True}
        )
        assert bob_assignment is not None

        # 2. Second execution (must be idempotent: no duplicates, actions marked 'updated')
        res2 = await seed_demo_data(db)
        assert res2["admin"]["action"] == "updated"
        for comp in res2["companies"]:
            assert comp["action"] == "updated"
        for u in res2["users"]:
            assert u["action"] == "updated"

        assert await db.users.count_documents({}) == 3
        assert await db.companies.count_documents({}) == 2
        assert await db.products.count_documents({}) == 12
        assert await db.customer_product_assignments.count_documents({"is_active": True}) == 2

        # 3. Test password reset procedure
        reset_ok = await reset_user_password(db, "alice@alphapharma.com", "NewValidCustPass123!")
        assert reset_ok is True
        alice_updated = await db.users.find_one({"email": "alice@alphapharma.com"})
        assert verify_password("NewValidCustPass123!", alice_updated["password_hash"]) is True

        # Clean up test database
        await client.drop_database(test_db_name)
    finally:
        await client.close()
