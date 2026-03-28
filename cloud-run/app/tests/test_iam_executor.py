import pytest
from unittest.mock import patch, MagicMock
from app.iam_executor import IamExecutor


def test_normalize_action():
    """_normalize_actionメソッドのテスト。"""
    assert IamExecutor._normalize_action("GRANT") == "GRANT"
    assert IamExecutor._normalize_action("grant") == "GRANT"
    assert IamExecutor._normalize_action("REVOKE") == "REVOKE"
    assert IamExecutor._normalize_action("revoke") == "REVOKE"
    assert IamExecutor._normalize_action("AnythingElse") == "GRANT"


def test_to_member():
    """_to_memberメソッドのテスト。"""
    assert IamExecutor._to_member("user@example.com") == "user:user@example.com"
    assert IamExecutor._to_member("sa@project.iam" ".gserviceaccount.com") == (
        "serviceAccount:sa@project.iam" ".gserviceaccount.com"
    )
    assert (
        IamExecutor._to_member("group:group@example.com") == "group:group@example.com"
    )
    assert IamExecutor._to_member(
        "serviceAccount:another-sa@project.iam.gserviceaccount.com"
    ) == ("serviceAccount:another-sa@project.iam" ".gserviceaccount.com")


def test_parse_resource():
    """_parse_resourceメソッドのテスト。"""
    assert IamExecutor._parse_resource("projects/my-project") == (
        "projects",
        "my-project",
    )
    assert IamExecutor._parse_resource("folders/12345") == ("folders", "12345")
    assert IamExecutor._parse_resource("organizations/67890") == (
        "organizations",
        "67890",
    )
    with pytest.raises(ValueError, match="unsupported resource_name format"):
        IamExecutor._parse_resource("buckets/my-bucket")


@patch("app.iam_executor.discovery")
def test_get_policy_project(mock_discovery):
    """_get_policyがプロジェクトに対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    executor._get_policy("projects/my-project")
    mock_service.projects().getIamPolicy.assert_called_with(
        resource="projects/my-project"
    )


@patch("app.iam_executor.discovery")
def test_get_policy_folder(mock_discovery):
    """_get_policyがフォルダに対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    executor._get_policy("folders/12345")
    mock_service.folders().getIamPolicy.assert_called_with(resource="folders/12345")


@patch("app.iam_executor.discovery")
def test_get_policy_organization(mock_discovery):
    """_get_policyが組織に対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    executor._get_policy("organizations/67890")
    mock_service.organizations().getIamPolicy.assert_called_with(
        resource="organizations/67890"
    )


@patch("app.iam_executor.discovery")
def test_get_policy_unsupported(mock_discovery):
    """サポートされていないリソースタイプの場合に_get_policyがValueErrorを送出するかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    with pytest.raises(ValueError):
        executor._get_policy("buckets/my-bucket")


@patch("app.iam_executor.discovery")
def test_set_policy_project(mock_discovery):
    """_set_policyがプロジェクトに対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    policy = {"bindings": []}
    executor._set_policy("projects/my-project", policy)
    mock_service.projects().setIamPolicy.assert_called_with(
        resource="projects/my-project", body={"policy": policy}
    )


@patch("app.iam_executor.discovery")
def test_set_policy_folder(mock_discovery):
    """_set_policyがフォルダに対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    policy = {"bindings": []}
    executor._set_policy("folders/12345", policy)
    mock_service.folders().setIamPolicy.assert_called_with(
        resource="folders/12345", body={"policy": policy}
    )


@patch("app.iam_executor.discovery")
def test_set_policy_organization(mock_discovery):
    """_set_policyが組織に対して正しく呼び出されるかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    policy = {"bindings": []}
    executor._set_policy("organizations/67890", policy)
    mock_service.organizations().setIamPolicy.assert_called_with(
        resource="organizations/67890", body={"policy": policy}
    )


@patch("app.iam_executor.discovery")
def test_set_policy_unsupported(mock_discovery):
    """サポートされていないリソースタイプの場合に_set_policyがValueErrorを送出するかのテスト。

    Args:
        mock_discovery: discovery.buildのモック。
    """
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    executor = IamExecutor()
    with pytest.raises(ValueError):
        executor._set_policy("buckets/my-bucket", {})
