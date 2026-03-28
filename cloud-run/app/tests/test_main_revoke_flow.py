from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from app.main import app
from app.models import ExpiredAccessRequest


@pytest.fixture
def client() -> FlaskClient:
    """テスト用のFlaskクライアントを返します。

    Returns:
        FlaskClient: Flaskアプリケーションのテストクライアント。
    """
    return app.test_client()


@patch("app.main.iam_executor")
@patch("app.main.repo")
@patch("app.main._authorize", return_value=True)
def test_revoke_expired_permissions_when_permission_exists(
    mock_authorize: MagicMock,
    mock_repo: MagicMock,
    mock_iam_executor: MagicMock,
    client: FlaskClient,
):
    """期限切れ権限の取り消し（権限が存在する場合）のテスト。

    Args:
        mock_authorize (MagicMock): 認証のモック。
        mock_repo (MagicMock): リポジトリのモック。
        mock_iam_executor (MagicMock): IAM Executorのモック。
        client (FlaskClient): テスト用のFlaskクライアント。
    """
    # Arrange
    expired_req = ExpiredAccessRequest(
        request_id="req-1",
        request_type="GRANT",
        principal_email="user@example.com",
        resource_name="projects/p1",
        role="roles/viewer",
        status="APPROVED",
        approved_at=None,
        expires_at=None,
        is_permission_active=True,
        reason="test reason",
    )
    mock_repo.search_expired_approved_access_requests.return_value = [expired_req]
    mock_iam_executor.execute.return_value.result = "SUCCESS"

    # Act
    response = client.post("/revoke_expired_permissions")

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["revoked"] == 1
    assert json_data["skipped"] == 0
    assert json_data["failed"] == 0

    # Verify that get_iam_policy_permission was NOT called
    mock_repo.get_iam_policy_permission.assert_not_called()

    # Verify that iam_executor.execute was called with a REVOKE request
    mock_iam_executor.execute.assert_called_once()
    call_args, _ = mock_iam_executor.execute.call_args
    executed_req = call_args[0]
    assert executed_req.request_type == "REVOKE"
    assert executed_req.request_id == "req-1"

    # Verify status was updated to REVOKED
    mock_repo.update_request_status.assert_called_with("req-1", "REVOKED")


@patch("app.main.iam_executor")
@patch("app.main.repo")
@patch("app.main._authorize", return_value=True)
def test_revoke_expired_permissions_when_permission_is_gone(
    mock_authorize: MagicMock,
    mock_repo: MagicMock,
    mock_iam_executor: MagicMock,
    client: FlaskClient,
):
    """期限切れ権限の取り消し（権限が既にない場合）のテスト。

    Args:
        mock_authorize (MagicMock): 認証のモック。
        mock_repo (MagicMock): リポジトリのモック。
        mock_iam_executor (MagicMock): IAM Executorのモック。
        client (FlaskClient): テスト用のFlaskクライアント。
    """
    # Arrange
    expired_req = ExpiredAccessRequest(
        request_id="req-2",
        request_type="GRANT",
        principal_email="user@example.com",
        resource_name="projects/p2",
        role="roles/editor",
        status="APPROVED",
        approved_at=None,
        expires_at=None,
        is_permission_active=False,
        reason="test reason",
    )
    mock_repo.search_expired_approved_access_requests.return_value = [expired_req]

    # Act
    response = client.post("/revoke_expired_permissions")

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["revoked"] == 0
    assert json_data["skipped"] == 1
    assert json_data["failed"] == 0

    # Verify that get_iam_policy_permission was NOT called
    mock_repo.get_iam_policy_permission.assert_not_called()

    # Verify that iam_executor.execute was NOT called
    mock_iam_executor.execute.assert_not_called()

    # Verify status was updated to REVOKED_ALREADY_GONE
    mock_repo.update_request_status.assert_called_with(
        "req-2", "REVOKED_ALREADY_GONE"
    )
