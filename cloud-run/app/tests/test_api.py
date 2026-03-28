from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from flask.testing import FlaskClient

from app.main import app


@pytest.fixture
def client() -> FlaskClient:
    return app.test_client()


@pytest.fixture
def mock_repo():
    with patch("app.main.repo", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_auth():
    with patch("app.main._authorize", return_value=True) as mock:
        yield mock


def test_api_create_request(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.insert_access_request_raw.return_value = None
    response = client.post("/api/requests", json={"request_id": "test"})
    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    mock_repo.insert_access_request_raw.assert_called_once()


def test_api_update_request_status(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.update_request_status.return_value = None
    response = client.put("/api/requests/123/status", json={"status": "APPROVED"})
    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    mock_repo.update_request_status.assert_called_once_with("123", "APPROVED")


def test_api_create_history(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.insert_request_history_event.return_value = None
    response = client.post("/api/history", json={"history_id": "test"})
    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    mock_repo.insert_request_history_event.assert_called_once()
