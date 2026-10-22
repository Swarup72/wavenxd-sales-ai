import asyncio
import sys

from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.repositories.indexes import create_indexes
from app.services.catalog_seed import seed_catalog


async def main() -> int:
    settings = get_settings()
    print(f"Connecting to database '{settings.mongodb_database}'...")

    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        database = client[settings.mongodb_database]

        # Verify connectivity
        await database.command("ping")
        print("Database ping successful.")

        # Ensure indexes are created
        print("Ensuring MongoDB indexes...")
        created_indexes = await create_indexes(database)
        for collection, indexes in created_indexes.items():
            print(f"  [{collection}] indexes ensured: {', '.join(indexes)}")

        # Seed catalog
        print("Seeding verified product catalog...")
        result = await seed_catalog(database)
        print(
            f"Catalog seed complete: {result['inserted']} inserted, "
            f"{result['updated']} updated, {result['total']} verified products."
        )
        return 0
    except Exception as exc:
        print(f"Error during catalog seed: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()
        print("Database client closed.")


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
