from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from google.cloud import asset_v1


class IamPolicyCollector:
    """Cloud Asset InventoryからIAMポリシーを収集するクラス。"""

    def __init__(self, target_project_id: str, target_org_id: str) -> None:
        self._target_project_id = target_project_id
        self._target_org_id = target_org_id
        self._client = asset_v1.AssetServiceClient()

    def collect_rows(
        self, execution_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, int], str]:
        scope = self._resolve_scope()
        assessment_timestamp = datetime.now(timezone.utc).isoformat()

        rows: list[dict[str, Any]] = []
        counts = {"policies": 0, "bindings": 0}

        # 外部システムと同様に単一スコープでIAMポリシーを検索
        response = self._client.search_all_iam_policies(request={"scope": scope})

        for result in response:
            counts["policies"] += 1
            resource_name = (
                re.sub(r"^//[^/]+/", "", result.resource)
                if result.resource.startswith("//")
                else result.resource
            )
            asset_type = result.asset_type
            policy = result.policy

            for binding in policy.bindings:
                role = binding.role
                for member in binding.members:
                    counts["bindings"] += 1
                    if ":" in member:
                        p_type_raw, p_email = member.split(":", 1)
                        # スキーマに合わせて型を正規化
                        p_type = (
                            "SERVICE_ACCOUNT"
                            if p_type_raw.lower() == "serviceaccount"
                            else p_type_raw.upper()
                        )
                    else:
                        p_type = "UNKNOWN"
                        p_email = member

                    # 重い expand_member は行わず、生のバインディング情報をそのままDBへ流す
                    rows.append(
                        {
                            "execution_id": execution_id,
                            "assessment_timestamp": assessment_timestamp,
                            "scope": scope,
                            "resource_type": asset_type,
                            "resource_name": resource_name,
                            "principal_type": p_type,
                            "principal_email": p_email,
                            "role": role,
                        }
                    )

        return rows, counts, scope

    def _resolve_scope(self) -> str:
        if self._target_org_id:
            return f"organizations/{self._target_org_id}"
        if self._target_project_id:
            return f"projects/{self._target_project_id}"
        raise ValueError("either target_org_id or target_project_id is required")
