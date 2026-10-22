from datetime import timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from app.core.security import hash_token
from app.models.common import utc_now
from app.models.session import Session
from app.services.session_service import (
    create_session,
    get_session_by_token,
    revoke_all_user_sessions,
    revoke_session,
)


class MockSessionCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.counter = 1

    async def insert_one(self, doc):
        d = dict(doc)
        d["_id"] = ObjectId()
        self.docs[d["session_token_hash"]] = d
        res = MagicMock()
        res.inserted_id = d["_id"]
        return res

    async def find_one(self, filter_dict):
        th = filter_dict.get("session_token_hash")
        return self.docs.get(th)

    async def update_one(self, filter_dict, update_dict):
        th = filter_dict.get("session_token_hash")
        doc = self.docs.get(th)
        res = MagicMock()
        if doc and (not filter_dict.get("is_revoked", False) or doc["is_revoked"] == filter_dict["is_revoked"]):
            for k, v in update_dict.get("$set", {}).items():
                doc[k] = v
            res.modified_count = 1
        else:
            res.modified_count = 0
        return res

    async def update_many(self, filter_dict, update_dict):
        uid = filter_dict.get("user_id")
        count = 0
        for doc in self.docs.values():
            if str(doc.get("user_id")) == str(uid) and not doc.get("is_revoked", False):
                for k, v in update_dict.get("$set", {}).items():
                    doc[k] = v
                count += 1
        res = MagicMock()
        res.modified_count = count
        return res



class MockDBForSessions:
    def __init__(self):
        self.sessions = MockSessionCollection()


@pytest.mark.anyio
async def test_session_creation_and_lookup():
    db = MockDBForSessions()
    user_id = ObjectId()

    session, raw_token = await create_session(
        database=db,
        user_id=user_id,
        user_agent="Mozilla/5.0 Test",
        ip_address="127.0.0.1",
        lifetime_seconds=3600,
    )

    # Raw token is high entropy and not equal to token hash
    assert raw_token != session.session_token_hash
    assert hash_token(raw_token) == session.session_token_hash
    assert session.user_id == user_id
    assert session.is_revoked is False
    assert len(session.csrf_token) >= 32

    # Successfully retrieved with raw token
    retrieved = await get_session_by_token(db, raw_token)
    assert retrieved is not None
    assert retrieved.session_token_hash == session.session_token_hash
    assert retrieved.user_id == user_id


@pytest.mark.anyio
async def test_expired_session_rejection():
    db = MockDBForSessions()
    user_id = ObjectId()

    # Session with negative lifetime (already expired)
    session, raw_token = await create_session(
        database=db,
        user_id=user_id,
        lifetime_seconds=-10,
    )

    retrieved = await get_session_by_token(db, raw_token)
    assert retrieved is None


@pytest.mark.anyio
async def test_revoked_session_rejection():
    db = MockDBForSessions()
    user_id = ObjectId()

    session, raw_token = await create_session(
        database=db,
        user_id=user_id,
        lifetime_seconds=3600,
    )

    # Valid before revocation
    assert await get_session_by_token(db, raw_token) is not None

    # Revoke session
    revoked = await revoke_session(db, raw_token)
    assert revoked is True

    # Rejected after revocation
    assert await get_session_by_token(db, raw_token) is None


@pytest.mark.anyio
async def test_revoke_all_user_sessions():
    db = MockDBForSessions()
    user_id = ObjectId()

    _, token1 = await create_session(db, user_id=user_id, lifetime_seconds=3600)
    _, token2 = await create_session(db, user_id=user_id, lifetime_seconds=3600)

    assert await get_session_by_token(db, token1) is not None
    assert await get_session_by_token(db, token2) is not None

    count = await revoke_all_user_sessions(db, user_id)
    assert count == 2

    assert await get_session_by_token(db, token1) is None
    assert await get_session_by_token(db, token2) is None
