"""
WaveNxD AI Sales Representative — Development Demo Data Seeder

Seeds:
1. MongoDB indexes for all collections
2. 12 Verified Product Catalog items
3. Administrator account (admin@wavenxd.com)
4. Customer Companies (Alpha Pharma Ltd, Beta Coatings Inc)
5. Customer Personas (alice@alphapharma.com, bob@betacoatings.com)
6. Scoped Product Assignments:
   - Alpha Pharma Ltd -> standard-nozzle-60khz
   - Beta Coatings Inc -> high-flow-conical-60khz

Usage:
    ./.venv/bin/python -m scripts.seed_demo_data
    ./.venv/bin/python -m scripts.seed_demo_data --reset-password <email> <new_password>
"""

import argparse
import asyncio
import sys

from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.services.demo_seed import (
    DEFAULT_DEMO_ADMIN_PASSWORD,
    DEFAULT_DEMO_CUSTOMER_PASSWORD,
    reset_user_password,
    seed_demo_data,
)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed idempotent development demo data for WaveNxD AI Sales Representative"
    )
    parser.add_argument(
        "--reset-password",
        nargs=2,
        metavar=("EMAIL", "NEW_PASSWORD"),
        help="Securely reset password for an existing user",
    )
    args = parser.parse_args()

    settings = get_settings()
    print("=" * 65)
    print(f"WaveNxD AI Sales Representative — Database Seeder")
    print(f"Target Database: {settings.mongodb_database}")
    print(f"Environment:     {settings.app_env}")
    print("=" * 65)

    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        database = client[settings.mongodb_database]
        await database.command("ping")
        print("✓ Connected to MongoDB successfully.\n")

        # Handle specific password reset request if invoked
        if args.reset_password:
            email, new_password = args.reset_password
            print(f"Resetting password for: {email}...")
            try:
                success = await reset_user_password(database, email, new_password)
                if success:
                    print(f"✓ Password successfully updated for '{email}'.")
                    return 0
                else:
                    print(f"✗ User '{email}' not found.", file=sys.stderr)
                    return 1
            except ValueError as err:
                print(f"✗ Password validation error: {err}", file=sys.stderr)
                return 1

        # Execute full idempotent demo seed
        print("Executing idempotent demo seed...")
        result = await seed_demo_data(database)

        print("\n--- Verified Product Catalog ---")
        cat = result["catalog"]
        print(f"  Inserted: {cat['inserted']}, Updated: {cat['updated']}, Total: {cat['total']}")

        print("\n--- Administrator Persona ---")
        adm = result["admin"]
        print(f"  Email:  {adm['email']}")
        print(f"  Role:   admin")
        print(f"  Action: {adm['action']}")

        print("\n--- Customer Companies ---")
        for comp in result["companies"]:
            print(f"  • {comp['name']} (ID: {comp['id']}, {comp['action']})")

        print("\n--- Customer Personas ---")
        for u in result["users"]:
            print(f"  • {u['full_name']} <{u['email']}>")
            print(f"    Company: {u['company_name']}")
            print(f"    Role:    {u['role']} ({u['action']})")

        print("\n--- Company Product Assignments ---")
        for a in result["assignments"]:
            print(f"  • [{a['company_name']}] -> {a['catalog_key']} ({a['product_name']})")

        print("\n" + "=" * 65)
        print("✓ Database seed complete and verified.")
        print(f"  Demo Customer Login: alice@alphapharma.com / {DEFAULT_DEMO_CUSTOMER_PASSWORD}")
        print(f"  Demo Customer Login: bob@betacoatings.com   / {DEFAULT_DEMO_CUSTOMER_PASSWORD}")
        print(f"  Demo Admin Login:    admin@wavenxd.com     / {DEFAULT_DEMO_ADMIN_PASSWORD}")
        print("=" * 65)
        return 0
    except Exception as exc:
        print(f"✗ Error during demo data seeding: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
