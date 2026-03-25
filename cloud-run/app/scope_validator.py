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
        self._crm = discovery.build("cloudresourcemanager", "v1", cache_discovery=False)
        self._org_cache: dict[str, str | None] = {}

    def validate_resource_name(self, resource_name: str) -> str | None:
        if not resource_name.startswith("projects/"):
            return "resource_name must be projects/{project_id}"

        project_id = resource_name.split("/", 1)[1].strip()
        if not project_id:
            return "resource_name must contain project id"

        # Project-only mode: enforce exact project match.
        if self._config.target_org_id == "":
            expected = self._config.target_project_id
            if expected and project_id != expected:
                return f"resource is out of managed scope: expected projects/{expected}, got {resource_name}"
            return None

        # Organization mode: allow only projects under the configured organization.
        org_id = self._get_org_id(project_id)
        if org_id is None:
            return f"failed to resolve organization for project: {project_id}"
        if org_id != self._config.target_org_id:
            return (
                "resource is out of managed organization scope: "
                f"expected organizations/{self._config.target_org_id}, got organizations/{org_id}"
            )
        return None

    def _get_org_id(self, project_id: str) -> str | None:
        if project_id in self._org_cache:
            return self._org_cache[project_id]

        try:
            res = self._crm.projects().getAncestry(projectId=project_id, body={}).execute()
        except HttpError:
            self._org_cache[project_id] = None
            return None

        ancestors = res.get("ancestor", [])
        for item in ancestors:
            resource_id = item.get("resourceId", {})
            if resource_id.get("type") == "organization":
                org_id = str(resource_id.get("id", "")).strip()
                self._org_cache[project_id] = org_id or None
                return self._org_cache[project_id]

        self._org_cache[project_id] = None
        return None
