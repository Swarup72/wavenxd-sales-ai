import asyncio
import sys

from bson import ObjectId
from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.domain.enums import UserRole
from app.services.invitation_service import create_invitation


async def main() -> int:
    settings = get_settings()
    print("=== WaveNxD AI Sales Representative — Create Customer Invitation ===")

    if len(sys.argv) < 4:
        print("Usage: python -m scripts.invite_user <admin_email> <company_id> <customer_email>")
        return 1

    admin_email = sys.argv[1].strip().lower()
    company_id_str = sys.argv[2].strip()
    customer_email = sys.argv[3].strip().lower()

    if not ObjectId.is_valid(company_id_str):
        print(f"Error: Invalid ObjectId for company: {company_id_str}", file=sys.stderr)
        return 1

    company_id = ObjectId(company_id_str)

    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        database = client[settings.mongodb_database]
        await database.command("ping")

        admin = await database.users.find_one({"email": admin_email, "role": UserRole.ADMIN})
        if not admin:
            print(f"Error: Administrator with email '{admin_email}' not found.", file=sys.stderr)
            return 1

        invitation, raw_token = await create_invitation(
            database=database,
            email=customer_email,
            company_id=company_id,
            invited_by_user_id=admin["_id"],
        )

        print("\nInvitation successfully generated!")
        print(f"Target Email: {invitation.email}")
        print(f"Company ID:   {invitation.company_id}")
        print(f"Expires At:   {invitation.expires_at.isoformat()}")
        print(f"Invitation Token (Deliver securely): {raw_token}")
        print(f"Token Hash stored in DB:             {invitation.invitation_token_hash[:16]}...")
        return 0
    except Exception as exc:
        print(f"Error generating invitation: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
