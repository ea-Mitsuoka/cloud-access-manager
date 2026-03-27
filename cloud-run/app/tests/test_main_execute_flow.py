from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from flask.testing import FlaskClient

# conftest.py で環境変数がモックされた状態でロードされる
from app.main import app
from app.models import AccessRequest, ExecutionResult

@pytest.fixture
def client() -> FlaskClient:
    return app.test_client()

@pytest.fixture
def mock_repo():
    with patch("app.main.repo", autospec=True) as mock:
        yield mock

@pytest.fixture
def mock_iam_executor():
    with patch("app.main.iam_executor", autospec=True) as mock:
        yield mock

@pytest.fixture
def mock_scope_validator():
    with patch("app.main.scope_validator", autospec=True) as mock:
        # デフォルトはスコープ内（エラーなし）とする
        mock.validate_resource_name.return_value = None
        yield mock

@pytest.fixture
def mock_auth():
    with patch("app.main._authorize", return_value=True) as mock:
        yield mock

def _create_dummy_request(status: str = "APPROVED") -> AccessRequest:
    return AccessRequest(
        request_id="req-core-123",
        request_type="GRANT",
        principal_email="user@example.com",
        resource_name="projects/my-managed-project",
        role="roles/viewer",
        status=status,
        approved_at=None,
    )

# -------------------------------------------------------------------
# コアビジネスロジックの担保テスト（ユースケース・テスト）
# -------------------------------------------------------------------

def test_execute_golden_path_success(
    client: FlaskClient, mock_repo, mock_iam_executor, mock_scope_validator, mock_auth
):
    """
    【要件1: 正常系】承認済みのリクエストが正しくIAM適用され、成功ログが記録されること
    """
    mock_repo.get_approved_request.return_value = _create_dummy_request("APPROVED")
    mock_repo.has_success_execution.return_value = False
    mock_iam_executor.execute.return_value = ExecutionResult(
        result="SUCCESS", action="GRANT", target="projects/my-managed-project", before_hash=None, after_hash="hash"
    )

    response = client.post("/execute", json={"request_id": "req-core-123"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"

    # IAM APIが確実に呼ばれたこと
    mock_iam_executor.execute.assert_called_once()
    # 実行ログが確実にDBに記録されたこと
    mock_repo.insert_change_log.assert_called_once()
    call_args = mock_repo.insert_change_log.call_args[0]
    assert call_args[1] == "req-core-123"  # request_id
    assert call_args[3].result == "SUCCESS"


def test_execute_idempotency_skip(
    client: FlaskClient, mock_repo, mock_iam_executor, mock_scope_validator, mock_auth
):
    """
    【要件2: 冪等性】すでに成功済みのリクエストは、IAM APIを叩かずにスキップすること
    """
    mock_repo.get_approved_request.return_value = _create_dummy_request("APPROVED")
    # すでに成功した実行履歴が存在する
    mock_repo.has_success_execution.return_value = True

    response = client.post("/execute", json={"request_id": "req-core-123"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SKIPPED"
    assert response.get_json()["reason"] == "idempotent_skip"

    # IAM APIが「絶対に」呼ばれていないこと（二重付与の防止）
    mock_iam_executor.execute.assert_not_called()


def test_execute_rejects_unapproved_status(
    client: FlaskClient, mock_repo, mock_iam_executor, mock_scope_validator, mock_auth
):
    """
    【要件3: 状態遷移】ステータスが APPROVED 以外（PENDING等）の場合は絶対に実行しないこと
    """
    mock_repo.get_approved_request.return_value = _create_dummy_request("PENDING")

    response = client.post("/execute", json={"request_id": "req-core-123"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SKIPPED"
    assert response.get_json()["reason"] == "status_not_approved"

    # IAM APIが「絶対に」呼ばれていないこと
    mock_iam_executor.execute.assert_not_called()


def test_execute_rejects_out_of_scope_resource(
    client: FlaskClient, mock_repo, mock_iam_executor, mock_scope_validator, mock_auth
):
    """
    【要件4: 管理スコープ保護】管理対象外のリソースに対する実行要求は 400 エラーで弾くこと
    """
    mock_repo.get_approved_request.return_value = _create_dummy_request("APPROVED")
    # スコープバリデーターがエラー文字列を返す
    mock_scope_validator.validate_resource_name.return_value = "resource is out of managed scope"

    response = client.post("/execute", json={"request_id": "req-core-123"})

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "OUT_OF_SCOPE"

    # IAM APIが「絶対に」呼ばれていないこと（権限昇格・横移動の防止）
    mock_iam_executor.execute.assert_not_called()

    # 弾いた事実が「失敗」としてDBに監査記録されること
    mock_repo.insert_change_log.assert_called_once()
    assert mock_repo.insert_change_log.call_args[0][3].result == "FAILED"


def test_execute_logs_failure_on_exception(
    client: FlaskClient, mock_repo, mock_iam_executor, mock_scope_validator, mock_auth
):
    """
    【要件5: フェイルセーフ監査】IAM APIの呼び出しで例外（権限不足など）が起きても、失敗ログをDBに残すこと
    """
    mock_repo.get_approved_request.return_value = _create_dummy_request("APPROVED")
    mock_repo.has_success_execution.return_value = False
    # IAM APIが予期せぬクラッシュを起こす
    mock_iam_executor.execute.side_effect = Exception("Google Cloud API is down")

    response = client.post("/execute", json={"request_id": "req-core-123"})

    assert response.status_code == 500
    assert response.get_json()["result"] == "FAILED"
    assert response.get_json()["error_message"] == "Google Cloud API is down"

    # 例外が起きても、絶対にDBへ失敗の監査ログを書き込むこと
    mock_repo.insert_change_log.assert_called_once()
    failed_log = mock_repo.insert_change_log.call_args[0][3]
    assert failed_log.result == "FAILED"
    assert failed_log.error_code == "Exception"
