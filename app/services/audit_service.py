"""
Audit log service for WaveNxD administrative actions.
Records security-sensitive actions: company changes, user updates, password resets,
product status modifications, and access assignments.
"""

import logging
from typing import Any

from bson import ObjectId

from app.models.common import utc_now
from app.models.user import User

logger = logging.getLogger(__name__)


async def record_audit_event(
    database: Any,
    admin_user: User,
    action: str,
    target_type: str,
    target_id: str | ObjectId,
    details: str,
) -> dict[str, Any]:
    """
    Records an administrative action in the audit_logs collection.
    """
    event = {
        "admin_id": admin_user.id,
        "admin_email": admin_user.email,
        "action": action.strip().upper(),
        "target_type": target_type.strip().lower(),
        "target_id": str(target_id),
        "details": details.strip(),
        "created_at": utc_now(),
    }
    try:
        res = await database.audit_logs.insert_one(event)
        event["_id"] = res.inserted_id
        logger.info(
            "Audit event [%s] on %s:%s by %s",
            action,
            target_type,
            target_id,
            admin_user.email,
        )
        return event
    except Exception as exc:
        logger.error("Failed to write audit event: %s", exc)
        return event


async def list_audit_events(
    database: Any,
    limit: int = 100,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieves the most recent audit events.
    """
    query: dict[str, Any] = {}
    if action:
        query["action"] = action.strip().upper()

    cursor = database.audit_logs.find(query).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    for d in docs:
        d["id"] = str(d.pop("_id", ""))
        if "admin_id" in d and isinstance(d["admin_id"], ObjectId):
            d["admin_id"] = str(d["admin_id"])
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        else:
            d["created_at"] = str(d.get("created_at", ""))
    return docs
