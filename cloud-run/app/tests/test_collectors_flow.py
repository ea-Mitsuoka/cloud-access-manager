from __future__ import annotations

from unittest.mock import patch
import pytest
from flask.testing import FlaskClient
from google.api_core.exceptions import PermissionDenied

# conftest.py で環境変数がモックされた状態でロードされる
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
    with patch("app.main.repo", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_resource_collector():
    """リソースコレクターのモックを作成します。

    Yields:
        unittest.mock.MagicMock: モック化されたリソースコレクターオブジェクト。
    """
    with patch("app.main.resource_collector", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_group_collector():
    """グループコレクターのモックを作成します。

    Yields:
        unittest.mock.MagicMock: モック化されたグループコレクターオブジェクト。
    """
    with patch("app.main.group_collector", autospec=True) as mock:
        mock.source = "cloudidentity"
        yield mock


@pytest.fixture
def mock_auth():
    """認証チェックを常に成功させるモックを作成します。

    Yields:
        unittest.mock.MagicMock: モック化された認証関数。
    """
    with patch("app.main._authorize", return_value=True) as mock:
        yield mock


# -------------------------------------------------------------------
# データ収集パイプライン（棚卸し）のシナリオテスト
@pytest.fixture
def mock_iam_policy_collector():
    with patch("app.main.iam_policy_collector", autospec=True) as mock:
        yield mock

# -------------------------------------------------------------------


def test_collect_resources_success(
    client: FlaskClient, mock_repo, mock_resource_collector, mock_auth
):
    """【要件1: 正常系】リソース情報が正常に収集され、DBへの追記と成功レポートが記録されること

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (unittest.mock.MagicMock): モック化されたリポジトリ。
        mock_resource_collector (unittest.mock.MagicMock): モック化されたリソースコレクター。
        mock_auth (unittest.mock.MagicMock): モック化された認証。
    """
    # 収集処理のモック（1件のダミーデータを返す）
    mock_resource_collector.collect_rows.return_value = (
        [{"resource_name": "projects/dummy"}],
        {"Project": 1},
        "projects/my-managed-project",
    )
    mock_repo.insert_resource_inventory_rows.return_value = 1

    response = client.post("/collect/resources", json={"execution_id": "exec-123"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    assert response.get_json()["inserted_rows"] == 1

    # 収集データがDBに書き込まれたこと
    mock_repo.insert_resource_inventory_rows.assert_called_once()

    # 成功レポートが書き込まれたこと
    mock_repo.insert_pipeline_job_report.assert_called_once()
    call_args = mock_repo.insert_pipeline_job_report.call_args[1]
    assert call_args["job_type"] == "RESOURCE_COLLECTION"
    assert call_args["result"] == "SUCCESS"


def test_collect_resources_permission_denied(
    client: FlaskClient, mock_repo, mock_resource_collector, mock_auth
):
    """【要件2: フェイルセーフ (権限不足)】API権限エラーが起きた場合、HTTP 200を返し、DBには FAILED_PERMISSION を残すこと

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (unittest.mock.MagicMock): モック化されたリポジトリ。
        mock_resource_collector (unittest.mock.MagicMock): モック化されたリソースコレクター。
        mock_auth (unittest.mock.MagicMock): モック化された認証。
    """
    mock_resource_collector.collect_rows.side_effect = PermissionDenied("No access")

    response = client.post("/collect/resources", json={"execution_id": "exec-123"})

    # PermissionDenied は Cloud Scheduler を失敗扱いにしないよう 200 で返す仕様
    assert response.status_code == 200
    assert response.get_json()["result"] == "FAILED_PERMISSION"

    # レポートが確実にDBに保存されたこと
    mock_repo.insert_pipeline_job_report.assert_called_once()
    call_args = mock_repo.insert_pipeline_job_report.call_args[1]
    assert call_args["job_type"] == "RESOURCE_COLLECTION"
    assert call_args["result"] == "FAILED_PERMISSION"
    assert "roles/cloudasset.viewer" in call_args["hint"]


def test_collect_groups_success(
    client: FlaskClient, mock_repo, mock_group_collector, mock_auth
):
    """【要件3: 正常系】グループとメンバーシップ情報が収集され、DBの洗替・追記が行われること

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (unittest.mock.MagicMock): モック化されたリポジトリ。
        mock_group_collector (unittest.mock.MagicMock): モック化されたグループコレクター。
        mock_auth (unittest.mock.MagicMock): モック化された認証。
    """
    mock_group_collector.collect.return_value = (
        [{"group_email": "g@example.com"}],
        [{"member_email": "m@example.com"}],
        {"groups": 1, "memberships": 1},
    )
    mock_repo.replace_groups.return_value = 1
    mock_repo.insert_group_membership_rows.return_value = 1

    response = client.post("/collect/groups", json={"execution_id": "exec-456"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    assert response.get_json()["groups_replaced"] == 1

    # グループは洗替（DELETE/INSERT）、メンバーは追記（INSERT）が呼ばれること
    mock_repo.replace_groups.assert_called_once()
    mock_repo.insert_group_membership_rows.assert_called_once()

    # 成功レポートが書き込まれたこと
    mock_repo.insert_pipeline_job_report.assert_called_once()
    assert mock_repo.insert_pipeline_job_report.call_args[1]["result"] == "SUCCESS"


def test_collect_groups_failure(
    client: FlaskClient, mock_repo, mock_group_collector, mock_auth
):
    """【要件4: フェイルセーフ (汎用エラー)】グループ収集APIが例外を起こした場合、500エラーを返し、DBに FAILED レポートを記録すること

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
        mock_repo (unittest.mock.MagicMock): モック化されたリポジトリ。
        mock_group_collector (unittest.mock.MagicMock): モック化されたグループコレクター。
        mock_auth (unittest.mock.MagicMock): モック化された認証。
    """
    mock_group_collector.collect.side_effect = Exception("Identity API is down")

    response = client.post("/collect/groups", json={"execution_id": "exec-456"})

    assert response.status_code == 500
    assert response.get_json()["result"] == "FAILED"
    assert response.get_json()["error_message"] == "Identity API is down"

    # レポートが確実にDBに保存されたこと
    mock_repo.insert_pipeline_job_report.assert_called_once()
    call_args = mock_repo.insert_pipeline_job_report.call_args[1]
    assert call_args["job_type"] == "GROUP_COLLECTION"
    assert call_args["result"] == "FAILED"


def test_collectors_reject_unauthorized(client: FlaskClient):
    """【要件5: セキュリティ】認証トークンがない場合、収集エンドポイントは 401 を返すこと

    Args:
        client (FlaskClient): テスト用のFlaskクライアント。
    """
    # mock_auth フィクスチャを渡していないため、_authorize は本来の挙動（False）になる
    resp_resources = client.post("/collect/resources")
    assert resp_resources.status_code == 401

    resp_groups = client.post("/collect/groups")
    assert resp_groups.status_code == 401


def test_collect_iam_policies_success(
    client: FlaskClient, mock_repo, mock_iam_policy_collector, mock_auth
):
    """【要件】IAMポリシーが正常に収集され、DBの洗い替えと成功レポートが記録されること"""
    mock_iam_policy_collector.collect_rows.return_value = (
        [{"resource_name": "projects/dummy", "role": "roles/viewer"}],
        {"policies": 1, "bindings": 1},
        "projects/my-managed-project",
    )
    mock_repo.replace_iam_policy_permissions.return_value = 1

    response = client.post("/collect/iam-policies", json={"execution_id": "exec-789"})

    assert response.status_code == 200
    assert response.get_json()["result"] == "SUCCESS"
    assert response.get_json()["inserted_rows"] == 1

    mock_repo.replace_iam_policy_permissions.assert_called_once()
    mock_repo.insert_pipeline_job_report.assert_called_once()
    assert (
        mock_repo.insert_pipeline_job_report.call_args[1]["job_type"]
        == "IAM_POLICY_COLLECTION"
    )
