from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from googleapiclient import discovery


class GoogleGroupCollector:
    """Googleグループとそのメンバーシップ情報を収集するクラス。"""

    def __init__(
        self, workspace_customer_id: str, source: str = "cloudidentity"
    ) -> None:
        """
        GoogleGroupCollectorを初期化します。

        Args:
            workspace_customer_id (str): Google Workspaceの顧客ID。
            source (str, optional): データソースを示す文字列。デフォルトは "cloudidentity"。
        """
        self._customer_id = workspace_customer_id or "my_customer"
        self._source = source
        self._api = discovery.build(
            "cloudidentity",
            "v1",
            cache_discovery=False,
        )

    @property
    def source(self) -> str:
        """データソースの識別子。"""
        return self._source

    def collect(
        self, execution_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """
        Googleグループとメンバーシップの情報を収集します。

        Args:
            execution_id (str): この収集ジョブのユニークID。

        Returns:
            tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
                - グループ情報の辞書のリスト。
                - メンバーシップ情報の辞書のリスト。
                - 収集されたグループとメンバーシップの数を含む辞書。
        """
        assessed_at = datetime.now(timezone.utc).isoformat()

        groups = self._fetch_groups()
        group_rows: list[dict[str, Any]] = []
        membership_rows: list[dict[str, Any]] = []

        for g in groups:
            group_name = str(g.get("name", "")).strip()  # groups/{id}
            group_email = str(g.get("groupKey", {}).get("id", "")).strip()
            if not group_name or not group_email:
                continue

            group_rows.append(
                {
                    "group_email": group_email,
                    "group_name": g.get("displayName"),
                    "description": g.get("description"),
                }
            )

            for m in self._fetch_memberships(group_name):
                member_email = str(
                    m.get("preferredMemberKey", {}).get("id", "")
                ).strip()
                if not member_email:
                    continue

                role_name = ""
                roles = m.get("roles", [])
                if roles:
                    role_name = str(roles[0].get("name", "")).strip()

                membership_rows.append(
                    {
                        "execution_id": execution_id,
                        "assessed_at": assessed_at,
                        "group_email": group_email,
                        "member_email": member_email,
                        "member_display_name": None,
                        "membership_type": role_name or None,
                        "source": self._source,
                    }
                )

        counts = {
            "groups": len(group_rows),
            "memberships": len(membership_rows),
        }
        return group_rows, membership_rows, counts

    def _fetch_groups(self) -> list[dict[str, Any]]:
        """
        Cloud Identity APIを使用して、顧客アカウント内のすべてのGoogleグループを取得します。

        Returns:
            list[dict[str, Any]]: 取得したグループのリスト。
        """
        # Cloud Identity query for Google Groups in the customer.
        query = (
            f"parent=='customers/{self._customer_id}'"
            " && 'cloudidentity.googleapis.com/groups.discussion_forum' in"
            " labels"
        )

        groups: list[dict[str, Any]] = []
        page_token = ""
        while True:
            resp = (
                self._api.groups()
                .search(
                    query=query,
                    pageSize=200,
                    pageToken=page_token,
                )
                .execute()
            )
            groups.extend(resp.get("groups", []))
            page_token = str(resp.get("nextPageToken", "")).strip()
            if not page_token:
                break
        return groups

    def _fetch_memberships(self, group_name: str) -> list[dict[str, Any]]:
        """
        指定されたグループのすべてのメンバーシップを取得します。

        Args:
            group_name (str): メンバーシップを取得するグループの名前 (例: "groups/12345")。

        Returns:
            list[dict[str, Any]]: 取得したメンバーシップのリスト。
        """
        memberships: list[dict[str, Any]] = []
        page_token = ""
        while True:
            resp = (
                self._api.groups()
                .memberships()
                .list(
                    parent=group_name,
                    pageSize=200,
                    pageToken=page_token,
                    view="FULL",
                )
                .execute()
            )
            memberships.extend(resp.get("memberships", []))
            page_token = str(resp.get("nextPageToken", "")).strip()
            if not page_token:
                break
        return memberships
