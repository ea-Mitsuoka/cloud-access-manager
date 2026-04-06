import pytest
from unittest.mock import MagicMock
from app.scope_validator import ScopeConfig, ScopeValidator

# --- Project-only Mode Tests ---


@pytest.fixture
def project_validator(monkeypatch):
    """プロジェクトモードのScopeValidator（モック化されたdiscovery.build付き）を提供します。"""
    mock_crm_service = MagicMock()
    monkeypatch.setattr(
        "app.scope_validator.discovery.build",
        lambda *args, **kwargs: mock_crm_service,
    )
    config = ScopeConfig(target_project_id="my-project", target_org_id="")
    validator = ScopeValidator(config)
    return validator


def test_project_mode_valid_project(project_validator):
    """プロジェクトモード：有効なプロジェクトのテスト。"""
    assert project_validator.validate_resource_name("projects/my-project") is None


def test_project_mode_invalid_project(project_validator):
    """プロジェクトモード：無効なプロジェクトのテスト。"""
    assert (
        project_validator.validate_resource_name("projects/another-project") is not None
    )


def test_project_mode_rejects_folder(project_validator):
    """プロジェクトモード：フォルダが拒否されるかのテスト。"""
    assert project_validator.validate_resource_name("folders/12345") is not None


def test_project_mode_rejects_organization(project_validator):
    """プロジェクトモード：組織が拒否されるかのテスト。"""
    assert project_validator.validate_resource_name("organizations/67890") is not None


# --- Organization Mode Tests ---


@pytest.fixture
def org_validator(monkeypatch):
    """組織モードのScopeValidator（モック化されたヘルパー付き）を提供します。"""
    # Mock discovery.build to prevent actual API calls during ScopeValidator init
    mock_crm_service = MagicMock()
    monkeypatch.setattr(
        "app.scope_validator.discovery.build",
        lambda *args, **kwargs: mock_crm_service,
    )

    config = ScopeConfig(target_project_id="any-project", target_org_id="11111")
    validator = ScopeValidator(config)

    # Mock the internal methods to avoid actual API calls
    def mock_get_project_org(project_id):
        if project_id == "proj-in-org":
            return "11111"
        if project_id == "proj-out-of-org":
            return "22222"
        return None

    def mock_get_folder_org(folder_name):
        if folder_name == "folders/folder-in-org":
            return "11111"
        if folder_name == "folders/folder-out-of-org":
            return "22222"
        return None

    monkeypatch.setattr(validator, "_get_project_org_id", mock_get_project_org)
    monkeypatch.setattr(validator, "_get_folder_org_id", mock_get_folder_org)
    return validator


def test_org_mode_valid_project(org_validator):
    """組織モード：有効なプロジェクトのテスト。"""
    assert org_validator.validate_resource_name("projects/proj-in-org") is None


def test_org_mode_invalid_project(org_validator):
    """組織モード：無効なプロジェクトのテスト。"""
    assert org_validator.validate_resource_name("projects/proj-out-of-org") is not None


def test_org_mode_unresolved_project(org_validator):
    """組織モード：解決できないプロジェクトのテスト。"""
    assert org_validator.validate_resource_name("projects/proj-unresolved") is not None
