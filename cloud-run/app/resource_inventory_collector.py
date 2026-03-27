from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from google.cloud import asset_v1
from google.protobuf.json_format import MessageToDict


class ResourceInventoryCollector:
    def __init__(self, target_project_id: str, target_org_id: str) -> None:
        self._target_project_id = target_project_id
        self._target_org_id = target_org_id
        self._client = asset_v1.AssetServiceClient()

    def collect_rows(
        self, execution_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, int], str]:
        scope = self._resolve_scope()
        assessed_at = datetime.now(timezone.utc).isoformat()
        note = f"source=cloudasset scope={scope}"

        request = asset_v1.SearchAllResourcesRequest(
            scope=scope,
            asset_types=[
                "cloudresourcemanager.googleapis.com/Folder",
                "cloudresourcemanager.googleapis.com/Project",
            ],
            page_size=500,
        )

        rows: list[dict[str, Any]] = []
        counts = Counter()

        for resource in self._client.search_all_resources(request=request):
            resource_type = self._to_resource_type(resource.asset_type)
            normalized_name = self._normalize_full_resource_name(resource.name)
            parent = self._normalize_full_resource_name(
                resource.parent_full_resource_name
            )
            resource_id = self._to_resource_id(resource_type, resource, normalized_name)

            rows.append(
                {
                    "execution_id": execution_id,
                    "assessed_at": assessed_at,
                    "resource_type": resource_type,
                    "resource_name": resource.display_name or resource_id,
                    "resource_id": resource_id,
                    "parent_resource_id": parent,
                    "full_resource_path": normalized_name,
                    "note": note,
                }
            )
            counts[resource_type] += 1

        return rows, dict(counts), scope

    def _resolve_scope(self) -> str:
        if self._target_org_id:
            return f"organizations/{self._target_org_id}"
        if self._target_project_id:
            return f"projects/{self._target_project_id}"
        raise ValueError("either target_org_id or target_project_id is required")

    @staticmethod
    def _to_resource_type(asset_type: str) -> str:
        if asset_type.endswith("/Folder"):
            return "Folder"
        if asset_type.endswith("/Project"):
            return "Project"
        return asset_type.rsplit("/", 1)[-1]

    @staticmethod
    def _normalize_full_resource_name(raw: str) -> str:
        if not raw:
            return ""
        value = raw.strip()
        value = value.removeprefix("//")
        value = value.removeprefix("cloudresourcemanager.googleapis.com/")
        if value.startswith("projects/") and value.count("/") > 1:
            value = value.removeprefix("projects/")

        m = re.search(r"(organizations/\d+|folders/\d+|projects/[^/]+)$", value)
        if m:
            return m.group(1)
        return value

    def _to_resource_id(
        self,
        resource_type: str,
        resource: asset_v1.ResourceSearchResult,
        normalized_name: str,
    ) -> str:
        if resource_type == "Folder":
            return normalized_name or "unknown-folder"

        if resource_type == "Project":
            attrs = (
                MessageToDict(resource.additional_attributes)
                if resource.additional_attributes
                else {}
            )
            project_id = str(attrs.get("projectId", "")).strip()
            if project_id:
                return project_id

            project_ref = str(resource.project or "").strip()
            if project_ref.startswith("projects/"):
                return project_ref.split("/", 1)[1]

            if normalized_name.startswith("projects/"):
                return normalized_name.split("/", 1)[1]

        return normalized_name or "unknown-resource"
