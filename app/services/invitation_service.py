from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from app.core.config import get_settings
from app.core.security import (
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
)
from app.domain.enums import InvitationStatus, UserRole
from app.models.common import utc_now
from app.models.invitation import Invitation
from app.models.user import User


class InvitationError(Exception):
    """Base exception for invitation errors."""


class InvitationNotFoundError(InvitationError):
    """Raised when an invitation token is invalid, expired, or already consumed."""


async def create_invitation(
    database: Any,
    email: str,
    company_id: ObjectId,
    invited_by_user_id: ObjectId,
    expiry_hours: int | None = None,
) -> tuple[Invitation, str]:
    """
    Creates an invitation for a customer user to join a specific company.
    Stores only the SHA-256 hash of the invitation token.
    Returns the Invitation model and raw token to be delivered securely.
    """
    settings = get_settings()
    normalized_email = email.strip().lower()

    # Verify company exists and is active
    company = await database.companies.find_one({"_id": company_id, "is_active": True})
    if not company:
        raise InvitationError("Target company does not exist or is inactive")

    # Check if active user already exists
    existing_user = await database.users.find_one({"email": normalized_email})
    if existing_user and existing_user.get("is_active"):
        raise InvitationError("An active user with this email already exists")

    raw_token = generate_secure_token(32)
    token_hash = hash_token(raw_token)

    hours = expiry_hours if expiry_hours is not None else settings.invitation_expiry_hours
    now = utc_now()
    expires_at = now + timedelta(hours=hours)

    invitation = Invitation(
        invitation_token_hash=token_hash,
        email=normalized_email,
        company_id=company_id,
        invited_by_user_id=invited_by_user_id,
        status=InvitationStatus.PENDING,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )

    doc = invitation.model_dump(by_alias=True, exclude={"id"})
    result = await database.invitations.insert_one(doc)
    invitation.id = result.inserted_id

    return invitation, raw_token


async def accept_invitation(
    database: Any,
    raw_token: str,
    password: str,
    full_name: str | None = None,
) -> User:
    """
    Accepts an invitation, sets the customer password, and creates the customer user.
    Uses a single-document conditional update to atomically mark the invitation consumed,
    preventing reuse or race conditions even on standalone MongoDB instances.
    """
    if not raw_token or not raw_token.strip():
        raise InvitationNotFoundError("Invalid or missing invitation token")

    token_hash = hash_token(raw_token.strip())

    # Validate password strength before modifying invitation state
    valid, err_msg = validate_password_strength(password)
    if not valid:
        raise InvitationError(err_msg or "Password does not meet strength requirements")

    now = utc_now()

    # Atomically mark the invitation as CONSUMED only if it is currently PENDING and unexpired
    invitation_doc = await database.invitations.find_one_and_update(
        {
            "invitation_token_hash": token_hash,
            "status": InvitationStatus.PENDING,
            "expires_at": {"$gt": now},
        },
        {
            "$set": {
                "status": InvitationStatus.CONSUMED,
                "consumed_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.BEFORE,
    )

    if not invitation_doc:
        raise InvitationNotFoundError(
            "Invitation is invalid, expired, or has already been used"
        )

    invitation = Invitation(**invitation_doc)
    pw_hash = hash_password(password)
    name = (full_name or "").strip() or invitation.email.split("@")[0].title()

    # Create or activate user strictly as CUSTOMER linked to invitation.company_id
    user = User(
        email=invitation.email,
        full_name=name,
        role=UserRole.CUSTOMER,
        company_id=invitation.company_id,
        password_hash=pw_hash,
        is_active=True,
        must_change_password=False,
        created_at=now,
        updated_at=now,
    )

    user_doc = user.model_dump(by_alias=True, exclude={"id"})
    existing = await database.users.find_one({"email": invitation.email})

    if existing:
        # Update existing inactive record
        await database.users.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "full_name": user.full_name,
                    "password_hash": user.password_hash,
                    "company_id": user.company_id,
                    "role": user.role,
                    "is_active": True,
                    "must_change_password": False,
                    "updated_at": now,
                }
            },
        )
        user.id = existing["_id"]
    else:
        result = await database.users.insert_one(user_doc)
        user.id = result.inserted_id

    # Record which user consumed this invitation
    await database.invitations.update_one(
        {"_id": invitation.id},
        {"$set": {"consumed_by_user_id": user.id}},
    )

    return user
