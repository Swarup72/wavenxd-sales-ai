from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from app.core.config import get_settings
from app.core.security import generate_secure_token, hash_token
from app.models.common import utc_now
from app.models.session import Session


async def create_session(
    database: Any,
    user_id: ObjectId,
    user_agent: str | None = None,
    ip_address: str | None = None,
    lifetime_seconds: int | None = None,
) -> tuple[Session, str]:
    """
    Creates a new server-side session for a user.
    Stores only the SHA-256 hash of the session token.
    Returns the created Session model and the raw session token to be set in the cookie.
    """
    settings = get_settings()
    raw_token = generate_secure_token(32)
    token_hash = hash_token(raw_token)
    csrf_token = generate_secure_token(32)

    seconds = lifetime_seconds if lifetime_seconds is not None else settings.session_max_age_seconds
    now = utc_now()
    expires_at = now + timedelta(seconds=seconds)
    uid = ObjectId(user_id) if isinstance(user_id, str) else user_id

    session = Session(
        session_token_hash=token_hash,
        user_id=uid,
        expires_at=expires_at,
        is_revoked=False,
        csrf_token=csrf_token,
        user_agent=user_agent,
        ip_address=ip_address,
        created_at=now,
        updated_at=now,
    )


    doc = session.model_dump(by_alias=True, exclude={"id"})
    result = await database.sessions.insert_one(doc)
    session.id = result.inserted_id

    return session, raw_token


async def get_session_by_token(
    database: Any,
    raw_session_token: str | None,
) -> Session | None:
    """
    Retrieves and validates a session by its raw token.
    Enforces that the session is not revoked and has not expired.
    """
    if not raw_session_token or not raw_session_token.strip():
        return None

    token_hash = hash_token(raw_session_token.strip())
    doc = await database.sessions.find_one({"session_token_hash": token_hash})
    if not doc:
        return None

    session = Session(**doc)

    if session.is_revoked:
        return None

    # Enforce UTC timezone awareness for accurate comparison
    now = utc_now()
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        return None

    return session


async def revoke_session(database: Any, raw_session_token: str | None) -> bool:
    """
    Revokes a single session by its raw token.
    """
    if not raw_session_token or not raw_session_token.strip():
        return False

    token_hash = hash_token(raw_session_token.strip())
    result = await database.sessions.update_one(
        {"session_token_hash": token_hash, "is_revoked": False},
        {"$set": {"is_revoked": True, "updated_at": utc_now()}},
    )
    return result.modified_count > 0


async def revoke_all_user_sessions(database: Any, user_id: ObjectId | str) -> int:
    """
    Revokes all active sessions for a user (e.g. upon password reset or security event).
    """
    uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
    result = await database.sessions.update_many(
        {"user_id": uid, "is_revoked": False},
        {"$set": {"is_revoked": True, "updated_at": utc_now()}},
    )
    return result.modified_count

