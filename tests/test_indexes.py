from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import ASCENDING, DESCENDING

from app.repositories.indexes import create_indexes


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []
        self.existing_indexes: set[str] = set()

    async def create_index(self, keys, **kwargs):
        index_name = kwargs.get("name", "unnamed")
        self.calls.append({"keys": keys, "kwargs": kwargs})
        self.existing_indexes.add(index_name)
        return index_name


class MockDatabase:
    def __init__(self):
        self.companies = MockCollection("companies")
        self.users = MockCollection("users")
        self.products = MockCollection("products")
        self.customer_product_assignments = MockCollection(
            "customer_product_assignments"
        )
        self.access_requests = MockCollection("access_requests")
        self.sessions = MockCollection("sessions")
        self.invitations = MockCollection("invitations")
        self.conversations = MockCollection("conversations")


@pytest.mark.anyio
async def test_every_expected_index_specification():
    db = MockDatabase()
    result = await create_indexes(db)

    # Companies
    assert len(db.companies.calls) == 1
    assert db.companies.calls[0]["keys"] == [("name", ASCENDING)]
    assert db.companies.calls[0]["kwargs"]["name"] == "company_name"

    # Users
    assert len(db.users.calls) == 2
    assert db.users.calls[0]["keys"] == [("email", ASCENDING)]
    assert db.users.calls[0]["kwargs"]["unique"] is True
    assert db.users.calls[0]["kwargs"]["name"] == "unique_user_email"

    assert db.users.calls[1]["keys"] == [
        ("company_id", ASCENDING),
        ("role", ASCENDING),
    ]
    assert db.users.calls[1]["kwargs"]["name"] == "users_by_company_and_role"

    # Products
    assert len(db.products.calls) == 3
    assert db.products.calls[0]["keys"] == [
        ("status", ASCENDING),
        ("name", ASCENDING),
    ]
    assert db.products.calls[0]["kwargs"]["name"] == "products_by_status_and_name"

    assert db.products.calls[1]["keys"] == [("applications", ASCENDING)]
    assert db.products.calls[1]["kwargs"]["name"] == "products_by_application"

    assert db.products.calls[2]["keys"] == [("catalog_key", ASCENDING)]
    assert db.products.calls[2]["kwargs"]["unique"] is True
    assert db.products.calls[2]["kwargs"]["sparse"] is True
    assert db.products.calls[2]["kwargs"]["name"] == "unique_product_catalog_key"

    # Customer Product Assignments
    assert len(db.customer_product_assignments.calls) == 2
    assert db.customer_product_assignments.calls[0]["keys"] == [
        ("company_id", ASCENDING),
        ("product_id", ASCENDING),
    ]
    assert db.customer_product_assignments.calls[0]["kwargs"]["unique"] is True
    assert (
        db.customer_product_assignments.calls[0]["kwargs"]["name"]
        == "unique_company_product_assignment"
    )

    assert db.customer_product_assignments.calls[1]["keys"] == [
        ("company_id", ASCENDING),
        ("is_active", ASCENDING),
    ]
    assert (
        db.customer_product_assignments.calls[1]["kwargs"]["name"]
        == "active_assignments_by_company"
    )

    # Access Requests
    assert len(db.access_requests.calls) == 3
    assert db.access_requests.calls[0]["keys"] == [
        ("company_id", ASCENDING),
        ("status", ASCENDING),
        ("created_at", DESCENDING),
    ]
    assert (
        db.access_requests.calls[0]["kwargs"]["name"]
        == "access_requests_by_company_status"
    )
    assert db.access_requests.calls[1]["keys"] == [
        ("status", ASCENDING),
        ("created_at", DESCENDING),
    ]
    assert (
        db.access_requests.calls[1]["kwargs"]["name"]
        == "access_requests_by_status"
    )
    assert db.access_requests.calls[2]["keys"] == [
        ("company_id", ASCENDING),
        ("product_id", ASCENDING),
        ("status", ASCENDING),
    ]
    assert (
        db.access_requests.calls[2]["kwargs"]["name"]
        == "access_requests_by_company_product_status"
    )

    # Sessions
    assert len(db.sessions.calls) == 3
    assert db.sessions.calls[0]["keys"] == [("session_token_hash", ASCENDING)]
    assert db.sessions.calls[0]["kwargs"]["unique"] is True
    assert db.sessions.calls[0]["kwargs"]["name"] == "unique_session_token_hash"
    assert db.sessions.calls[1]["keys"] == [("user_id", ASCENDING)]
    assert db.sessions.calls[1]["kwargs"]["name"] == "sessions_by_user_id"
    assert db.sessions.calls[2]["keys"] == [("expires_at", ASCENDING)]
    assert db.sessions.calls[2]["kwargs"]["name"] == "sessions_by_expires_at"

    # Invitations
    assert len(db.invitations.calls) == 3
    assert db.invitations.calls[0]["keys"] == [("invitation_token_hash", ASCENDING)]
    assert db.invitations.calls[0]["kwargs"]["unique"] is True
    assert db.invitations.calls[0]["kwargs"]["name"] == "unique_invitation_token_hash"
    assert db.invitations.calls[1]["keys"] == [("company_id", ASCENDING), ("status", ASCENDING)]
    assert db.invitations.calls[1]["kwargs"]["name"] == "invitations_by_company_status"
    assert db.invitations.calls[2]["keys"] == [("email", ASCENDING), ("status", ASCENDING)]
    assert db.invitations.calls[2]["kwargs"]["name"] == "invitations_by_email_status"

    # Conversations
    assert len(db.conversations.calls) == 2
    assert db.conversations.calls[0]["keys"] == [
        ("company_id", ASCENDING),
        ("user_id", ASCENDING),
        ("created_at", DESCENDING),
    ]
    assert (
        db.conversations.calls[0]["kwargs"]["name"]
        == "conversations_by_company_user_created"
    )
    assert db.conversations.calls[1]["keys"] == [("status", ASCENDING)]
    assert db.conversations.calls[1]["kwargs"]["name"] == "conversations_by_status"

    # Verify return dictionary contains all created index names
    assert result["companies"] == ["company_name"]
    assert result["users"] == ["unique_user_email", "users_by_company_and_role"]
    assert result["products"] == [
        "products_by_status_and_name",
        "products_by_application",
        "unique_product_catalog_key",
    ]
    assert result["customer_product_assignments"] == [
        "unique_company_product_assignment",
        "active_assignments_by_company",
    ]
    assert result["access_requests"] == [
        "access_requests_by_company_status",
        "access_requests_by_status",
        "access_requests_by_company_product_status",
    ]
    assert result["sessions"] == [
        "unique_session_token_hash",
        "sessions_by_user_id",
        "sessions_by_expires_at",
    ]
    assert result["invitations"] == [
        "unique_invitation_token_hash",
        "invitations_by_company_status",
        "invitations_by_email_status",
    ]
    assert result["conversations"] == [
        "conversations_by_company_user_created",
        "conversations_by_status",
    ]


@pytest.mark.anyio
async def test_repeated_index_initialization():
    db = MockDatabase()

    first_result = await create_indexes(db)
    second_result = await create_indexes(db)

    # Ensure running twice completes without error and returns identical index names
    assert first_result == second_result
    # Calls should simply repeat the ensure/create operation idempotently
    assert len(db.companies.calls) == 2
    assert len(db.users.calls) == 4
    assert len(db.products.calls) == 6
    assert len(db.customer_product_assignments.calls) == 4
    assert len(db.access_requests.calls) == 6
    assert len(db.sessions.calls) == 6
    assert len(db.invitations.calls) == 6
    assert len(db.conversations.calls) == 4


