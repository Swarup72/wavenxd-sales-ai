import argparse
import asyncio
import getpass
import os
import sys

from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.core.security import hash_password, validate_password_strength
from app.domain.enums import UserRole
from app.models.common import utc_now
from app.models.user import User


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="WaveNxD AI Sales Representative — Create Initial Administrator"
    )
    parser.add_argument("--email", help="Admin email address", default=None)
    parser.add_argument("--password", help="Admin password", default=None)
    parser.add_argument("--full-name", help="Admin full name", default=None)
    args = parser.parse_args()

    settings = get_settings()
    print("=== WaveNxD AI Sales Representative — Create Initial Administrator ===")

    email = (args.email or os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    if not email:
        if sys.stdin.isatty():
            email = input("Admin Email: ").strip().lower()
        else:
            print("Error: Admin email is required via --email or ADMIN_EMAIL env var.", file=sys.stderr)
            return 1

    if not email or "@" not in email:
        print("Error: A valid email address is required.", file=sys.stderr)
        return 1

    full_name = (args.full_name or os.environ.get("ADMIN_FULL_NAME") or "").strip()
    if not full_name:
        if sys.stdin.isatty():
            full_name = input("Admin Full Name: ").strip()
        else:
            full_name = "Admin Supervisor"

    password = args.password or os.environ.get("ADMIN_PASSWORD")
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Password: ")
            confirm_password = getpass.getpass("Confirm Password: ")
            if password != confirm_password:
                print("Error: Passwords do not match.", file=sys.stderr)
                return 1
        else:
            print("Error: Password is required via --password or ADMIN_PASSWORD env var.", file=sys.stderr)
            return 1

    valid, msg = validate_password_strength(password)
    if not valid:
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        database = client[settings.mongodb_database]
        await database.command("ping")

        existing = await database.users.find_one({"email": email})
        if existing:
            print(f"Error: User with email '{email}' already exists.", file=sys.stderr)
            return 1

        now = utc_now()
        pw_hash = hash_password(password)

        admin = User(
            email=email,
            full_name=full_name,
            role=UserRole.ADMIN,
            company_id=None,
            password_hash=pw_hash,
            is_active=True,
            must_change_password=False,
            created_at=now,
            updated_at=now,
        )

        doc = admin.model_dump(by_alias=True, exclude={"id"})
        result = await database.users.insert_one(doc)

        print(f"Successfully created Administrator account (ID: {result.inserted_id}) for '{email}'.")
        return 0
    except Exception as exc:
        print(f"Error creating administrator: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
