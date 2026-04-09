from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from flask.testing import FlaskClient

# conftest.pyでモックされた環境でappをインポートする
from app.main import app


@pytest.fixture
def client() -> FlaskClient:
    """テスト用のFlaskクライアントを返します。

    Returns:
        FlaskClient: Flaskアプリケーションのテストクライアント。
    """
    return app.test_client()


@pytest.fixture
def mock_repo():
    """リポジトリ（DBアクセサ）のモックを作成します。

    Yields:
        unittest.mock.MagicMock: モック化されたリポジトリオブジェクト。
    """
    with patch("app.main.repo", autospec=True) as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_auth():
    with patch("app.main._authorize", return_value=True) as mock:
        yield mock


@patch("app.main.logging.warning")
def test_reconcile_job_success_with_issues(
    mock_warning: MagicMock,
    client: FlaskClient,
    mock_repo: MagicMock,
    mock_auth: MagicMock,
):
    """リコンサイルジョブの成功ケース（不整合が検知された場合）をテストします。"""
    # Arrange
    mock_repo.run_reconciliation_job.return_value = 5

    # Act
    response = client.post("/reconcile", headers={"Authorization": "Bearer test-token"})

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["result"] == "SUCCESS"

    mock_repo.run_reconciliation_job.assert_called_once()

    # 🚨 5件の不整合があったので、警告ログが出力されているはず
    mock_warning.assert_called_once()
    assert "[RECONCILIATION_ISSUE_DETECTED]" in mock_warning.call_args[0][0]

    mock_repo.insert_pipeline_job_report.assert_called_once_with(
        execution_id=json_data["execution_id"],
        job_type="IAM_RECONCILIATION",
        result="SUCCESS",
        error_code=None,
        error_message=None,
        hint=None,
        counts={"inserted_issues": 5},
        details={"sql_file": "003_reconciliation.sql"},
    )


@patch("app.main.logging.warning")
def test_reconcile_job_success_no_issues(
    mock_warning: MagicMock,
    client: FlaskClient,
    mock_repo: MagicMock,
    mock_auth: MagicMock,
):
    """リコンサイルジョブの成功ケース（不整合がない場合）をテストします。"""
    # Arrange
    mock_repo.run_reconciliation_job.return_value = 0

    # Act
    response = client.post("/reconcile", headers={"Authorization": "Bearer test-token"})

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["result"] == "SUCCESS"

    mock_repo.run_reconciliation_job.assert_called_once()

    # 🟢 0件だったので、警告ログは絶対に出力されてはいけない
    mock_warning.assert_not_called()

    mock_repo.insert_pipeline_job_report.assert_called_once_with(
        execution_id=json_data["execution_id"],
        job_type="IAM_RECONCILIATION",
        result="SUCCESS",
        error_code=None,
        error_message=None,
        hint=None,
        counts={"inserted_issues": 0},
        details={"sql_file": "003_reconciliation.sql"},
    )


def test_reconcile_job_failure(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    """リコンサイルジョブの失敗ケースをテストします。

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (MagicMock): モック化されたリポジトリ。
    """
    # Arrange
    mock_repo.run_reconciliation_job.side_effect = Exception("BigQuery is down")

    # Act
    response = client.post("/reconcile", headers={"Authorization": "Bearer test-token"})

    # Assert
    assert response.status_code == 500
    json_data = response.get_json()
    assert json_data["result"] == "FAILED"
    assert json_data["error_code"] == "Exception"
    assert json_data["error_message"] == "BigQuery is down"

    mock_repo.run_reconciliation_job.assert_called_once()
    mock_repo.insert_pipeline_job_report.assert_called_once()
    call_args = mock_repo.insert_pipeline_job_report.call_args[1]
    assert call_args["job_type"] == "IAM_RECONCILIATION"
    assert call_args["result"] == "FAILED"
    assert call_args["error_code"] == "Exception"
    assert call_args["error_message"] == "BigQuery is down"


def test_update_iam_bindings_history_success(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    """IAMバインディング履歴更新ジョブの成功ケースをテストします。

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (MagicMock): モック化されたリポジトリ。
    """
    # Arrange
    mock_repo.run_update_raw_bindings_history_job.return_value = 10
    mock_repo.run_update_bindings_history_job.return_value = 10

    # Act
    response = client.post(
        "/jobs/update-iam-bindings-history",
        headers={"Authorization": "Bearer test-token"},
    )

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["result"] == "SUCCESS"
    assert json_data["inserted_rows"] == 10
    assert json_data["raw_inserted_rows"] == 10

    mock_repo.run_update_raw_bindings_history_job.assert_called_once_with(
        json_data["execution_id"]
    )
    mock_repo.run_update_bindings_history_job.assert_called_once_with(
        json_data["execution_id"]
    )
    mock_repo.insert_pipeline_job_report.assert_called_once_with(
        execution_id=json_data["execution_id"],
        job_type="IAM_BINDINGS_HISTORY_UPDATE",
        result="SUCCESS",
        error_code=None,
        error_message=None,
        hint=None,
        counts={"inserted_rows": 10, "raw_inserted_rows": 10},
        details={"note": "Includes principal catalog sync and raw history update"},
    )


def test_update_iam_bindings_history_failure(
    client: FlaskClient, mock_repo: MagicMock, mock_auth: MagicMock
):
    """IAMバインディング履歴更新ジョブの失敗ケースをテストします。

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (MagicMock): モック化されたリポジトリ。
    """
    # Arrange
    mock_repo.run_update_bindings_history_job.side_effect = Exception("Something broke")

    # Act
    response = client.post(
        "/jobs/update-iam-bindings-history",
        headers={"Authorization": "Bearer test-token"},
    )

    # Assert
    assert response.status_code == 500
    json_data = response.get_json()
    assert json_data["result"] == "FAILED"
    assert json_data["error_code"] == "Exception"
    assert json_data["error_message"] == "Something broke"

    mock_repo.run_update_bindings_history_job.assert_called_once()
    mock_repo.insert_pipeline_job_report.assert_called_once()
    call_args = mock_repo.insert_pipeline_job_report.call_args[1]
    assert call_args["job_type"] == "IAM_BINDINGS_HISTORY_UPDATE"
    assert call_args["result"] == "FAILED"
    assert call_args["error_code"] == "Exception"
    assert call_args["error_message"] == "Something broke"
