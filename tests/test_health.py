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


def test_database_health_reports_collections_and_startup_counts():
    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1.0})

    # Mock count_documents as AsyncMock
    for col_name in ("users", "companies", "products", "leads", "consultations"):
        col = MagicMock()
        col.count_documents = AsyncMock(return_value=12)
        setattr(mock_db, col_name, col)

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.close = AsyncMock()

    with (
        patch("app.main.AsyncMongoClient", return_value=mock_client),
        patch("app.main.create_indexes", new_callable=AsyncMock),
        patch("app.main.initialize_system_data", new_callable=AsyncMock) as mock_init,
    ):
        mock_init.return_value = {
            "startup_counts": {"users": 1, "companies": 2, "products": 12},
            "catalog": {},
            "seed_result": None,
        }
        with TestClient(app) as client:
            response = client.get("/health/db")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "wavenxd_sales"
            assert "collections" in data
            assert data["collections"]["users"] == 12
            assert data["startup_counts"]["users"] == 1


