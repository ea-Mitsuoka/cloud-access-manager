from __future__ import annotations

from dataclasses import dataclass

from googleapiclient import discovery
from googleapiclient.errors import HttpError


@dataclass(frozen=True)
class ScopeConfig:
    target_project_id: str
    target_org_id: str


class ScopeValidator:
    def __init__(self, config: ScopeConfig) -> None:
        self._config = config
        self._crm = discovery.build("cloudresourcemanager", "v3", cache_discovery=False)
        self._org_cache: dict[str, str | None] = {}

    def validate_resource_name(self, resource_name: str) -> str | None:
        if self._config.target_org_id == "":
            # Project-only mode: only allow the target project
            if resource_name != f"projects/{self._config.target_project_id}":
                return (
                    "resource is out of managed scope: expected "
                    f"projects/{self._config.target_project_id}, got {resource_name}"
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
                "resource_name must start with projects/, folders/, or organizations/"
            )

        if org_id is None:
            return f"failed to resolve organization for resource: {resource_name}"
        if org_id != self._config.target_org_id:
            return (
                "resource is out of managed organization scope: expected "
                f"organizations/{self._config.target_org_id}, got "
                f"organizations/{org_id}"
            )
        return None

    def _get_folder_org_id(self, folder_name: str) -> str | None:
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
