from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def mock_mongo():
    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1.0})
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.close = AsyncMock()

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        yield {
            "client": mock_client,
            "database": mock_db,
        }


def test_health_endpoint(mock_mongo):
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_endpoint(mock_mongo):
    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "wavenxd_sales"
    mock_mongo["database"].command.assert_awaited_with("ping")


def test_database_health_fails_when_ping_fails():
    mock_db = MagicMock()
    # Ping succeeds on startup, but fails when /health/db is called
    mock_db.command = AsyncMock(
        side_effect=[{"ok": 1.0}, ConnectionError("DB dropped")]
    )
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.close = AsyncMock()

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health/db")
            assert response.status_code >= 500

