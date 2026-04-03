from __future__ import annotations

import threading
from dataclasses import dataclass

from googleapiclient import discovery
from googleapiclient.errors import HttpError


@dataclass(frozen=True)
class ScopeConfig:
    """
    管理スコープの設定を保持するデータクラス。

    Attributes:
        target_project_id (str): プロジェクトモードの場合の対象プロジェクトID。
        target_org_id (str): 組織モードの場合の対象組織ID。
    """

    target_project_id: str
    target_org_id: str


class ScopeValidator:
    """リソースが管理スコープ内にあるかを検証するクラス。"""

    def __init__(self, config: ScopeConfig) -> None:
        """
        ScopeValidatorを初期化します。

        Args:
            config (ScopeConfig): 管理スコープの設定。
        """
        self._config = config
        self._org_cache: dict[str, str | None] = {}
        self._local = threading.local()

    @property
    def _crm(self):
        if not hasattr(self._local, "crm"):
            self._local.crm = discovery.build(
                "cloudresourcemanager", "v3", cache_discovery=False
            )
        return self._local.crm

    def validate_resource_name(self, resource_name: str) -> str | None:
        """
        指定されたリソース名が管理スコープ内にあるかを検証します。

        Args:
            resource_name (str): 検証するリソースの完全な名前。

        Returns:
            str | None: リソースがスコープ外の場合、エラーメッセージを返します。
                        スコープ内の場合はNoneを返します。
        """
        if self._config.target_org_id == "":
            # Project-only mode: only allow the target project
            if resource_name != f"projects/{self._config.target_project_id}":
                return (
                    "resource is out of managed scope: expected "
                    f"projects/{self._config.target_project_id}, got "
                    f"{resource_name}"
                )
            return None

        # Organization mode
        if resource_name.startswith("projects/"):
            project_id = resource_name.split("/", 1)[1].strip()
            if not project_id:
                return "resource_name must contain project id"
            org_id = self._get_project_org_id(project_id)
        elif resource_name.startswith("folders/"):
            org_id = self._get_folder_org_id(resource_name)
        elif resource_name.startswith("organizations/"):
            org_id = resource_name.split("/", 1)[1].strip()
        else:
            return (
                "resource_name must start with projects/, folders/, or "
                "organizations/"
            )

        if org_id is None:
            return "failed to resolve organization for resource: {}".format(
                resource_name
            )
        if org_id != self._config.target_org_id:
            return (
                "resource is out of managed organization scope: expected "
                f"organizations/{self._config.target_org_id}, got "
                f"organizations/{org_id}"
            )
        return None

    def _get_folder_org_id(self, folder_name: str) -> str | None:
        """
        指定されたフォルダが属する組織IDを取得します。

        結果はキャッシュされます。

        Args:
            folder_name (str): フォルダの完全な名前 (例: "folders/12345")。

        Returns:
            str | None: 組織ID。見つからない場合はNone。
        """
        if folder_name in self._org_cache:
            return self._org_cache[folder_name]

        try:
            folder = self._crm.folders().get(name=folder_name).execute()
            parent = folder.get("parent")
            if not parent:
                self._org_cache[folder_name] = None
                return None

            if parent.startswith("organizations/"):
                org_id = parent.split("/", 1)[1]
                self._org_cache[folder_name] = org_id
                return org_id

            if parent.startswith("folders/"):
                return self._get_folder_org_id(parent)

            self._org_cache[folder_name] = None
            return None

        except HttpError:
            self._org_cache[folder_name] = None
            return None

    def _get_project_org_id(self, project_id: str) -> str | None:
        """
        指定されたプロジェクトが属する組織IDを取得します。

        結果はキャッシュされます。

        Args:
            project_id (str): プロジェクトID (例: "my-project-id")。

        Returns:
            str | None: 組織ID。見つからない場合はNone。
        """
        if project_id in self._org_cache:
            return self._org_cache[project_id]

        try:
            project_name = f"projects/{project_id}"
            project = self._crm.projects().get(name=project_name).execute()
            parent = project.get("parent")

            if not parent:
                self._org_cache[project_id] = None
                return None

            if parent.startswith("organizations/"):
                org_id = parent.split("/", 1)[1]
                self._org_cache[project_id] = org_id
                return org_id

            if parent.startswith("folders/"):
                return self._get_folder_org_id(parent)

            self._org_cache[project_id] = None
            return None

        except HttpError:
            self._org_cache[project_id] = None
            return None
