from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.main import lifespan


@pytest.mark.anyio
async def test_startup_ordering_success():
    call_order: list[str] = []

    mock_db = MagicMock()

    async def mock_ping(*args, **kwargs):
        call_order.append("ping")
        return {"ok": 1.0}

    mock_db.command = AsyncMock(side_effect=mock_ping)

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    async def mock_close():
        call_order.append("client_close")

    mock_client.close = AsyncMock(side_effect=mock_close)

    async def mock_create_indexes(db):
        call_order.append("create_indexes")
        return {}

    test_app = FastAPI()

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", side_effect=mock_create_indexes),
    ):
        async with lifespan(test_app):
            call_order.append("serve_requests")
            assert test_app.state.mongo_client is mock_client
            assert test_app.state.database is mock_db

    # Verify complete ordering:
    # 1. ping
    # 2. create_indexes
    # 3. serve_requests
    # 4. client_close
    assert call_order == ["ping", "create_indexes", "serve_requests", "client_close"]


@pytest.mark.anyio
async def test_startup_cleanup_on_ping_failure():
    call_order: list[str] = []

    mock_db = MagicMock()

    async def mock_ping_fail(*args, **kwargs):
        call_order.append("ping_failed")
        raise ConnectionError("MongoDB connection refused")

    mock_db.command = AsyncMock(side_effect=mock_ping_fail)

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    async def mock_close():
        call_order.append("client_close")

    mock_client.close = AsyncMock(side_effect=mock_close)

    test_app = FastAPI()

    with patch("app.main.AsyncMongoClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Database connection verification failed"):
            async with lifespan(test_app):
                pass

    # Verify client was cleanly closed and no requests served
    assert call_order == ["ping_failed", "client_close"]
    mock_client.close.assert_awaited_once()


@pytest.mark.anyio
async def test_startup_cleanup_on_index_creation_failure():
    call_order: list[str] = []

    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1.0})

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    async def mock_close():
        call_order.append("client_close")

    mock_client.close = AsyncMock(side_effect=mock_close)

    async def mock_create_indexes_fail(db):
        call_order.append("create_indexes_failed")
        raise RuntimeError("Index creation syntax error")

    test_app = FastAPI()

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", side_effect=mock_create_indexes_fail),
    ):
        with pytest.raises(RuntimeError, match="Database index initialization failed"):
            async with lifespan(test_app):
                pass

    # Verify client was cleanly closed and no requests served
    assert call_order == ["create_indexes_failed", "client_close"]
    mock_client.close.assert_awaited_once()
