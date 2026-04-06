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


def test_api_create_requests_bulk(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.insert_access_requests_raw_bulk.return_value = None
    response = client.post(
        "/api/requests/bulk", json={"requests": [{"request_id": "r1"}]}
    )
    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    assert response.get_json()["inserted_count"] == 1
    mock_repo.insert_access_requests_raw_bulk.assert_called_once()


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


def test_api_create_history_bulk(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.insert_request_history_events_bulk.return_value = None
    response = client.post("/api/history/bulk", json={"events": [{"history_id": "h1"}]})
    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    assert response.get_json()["inserted_count"] == 1
    mock_repo.insert_request_history_events_bulk.assert_called_once()


def test_api_bulk_review_partial_success(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.bulk_update_request_status_and_history_detailed.return_value = {
        "updated": [{"request_id": "r1", "status": "APPROVED"}],
        "skipped": [],
        "errors": [],
    }
    with patch(
        "app.main._execute_request_by_id",
        return_value=(
            {"request_id": "r1", "result": "FAILED", "error_message": "x"},
            500,
        ),
    ):
        response = client.post(
            "/api/v1/requests/bulk-review",
            json={
                "reviews": [{"request_id": "r1", "status": "承認済"}],
                "actor_email": "approver@example.com",
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["result"] == "FAILED"
    assert len(body["failed"]) == 1


def test_api_get_statuses(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    mock_repo.get_status_master.return_value = {
        "承認済": "APPROVED",
        "申請中": "PENDING",
    }
    response = client.get("/api/statuses")
    assert response.status_code == 200
    data = response.get_json()
    assert data["mapping"]["承認済"] == "APPROVED"
    assert data["mapping"]["APPROVED"] == "APPROVED"
    mock_repo.get_status_master.assert_called_once()
