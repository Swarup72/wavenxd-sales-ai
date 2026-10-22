import pytest
from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.repositories.indexes import create_indexes
from app.services.catalog_seed import seed_catalog


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_mongodb_indexes_and_catalog_seed():
    settings = get_settings()
    test_db_name = f"{settings.mongodb_database}_integration_test"
    client = AsyncMongoClient(settings.mongodb_uri)

    try:
        # Check connection
        await client.admin.command("ping")
        db = client[test_db_name]

        # Clean collection for test run
        await db.products.drop()

        # 1. Create indexes on real MongoDB
        created = await create_indexes(db)
        assert "unique_product_catalog_key" in created["products"]

        # Verify product indexes in MongoDB
        product_indexes = await db.products.index_information()
        assert "unique_product_catalog_key" in product_indexes
        assert product_indexes["unique_product_catalog_key"]["unique"] is True

        # 2. First seed run
        res1 = await seed_catalog(db)
        assert res1["inserted"] == 12
        assert res1["updated"] == 0
        assert await db.products.count_documents({}) == 12

        # 3. Second seed run (idempotency verification on real MongoDB)
        res2 = await seed_catalog(db)
        assert res2["inserted"] == 0
        assert res2["updated"] == 12
        assert await db.products.count_documents({}) == 12

        # Clean up test database
        await client.drop_database(test_db_name)
    finally:
        await client.close()
