from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from googleapiclient import discovery


class GoogleGroupCollector:
    def __init__(self, workspace_customer_id: str, source: str = "cloudidentity") -> None:
        self._customer_id = workspace_customer_id or "my_customer"
        self._source = source
        self._api = discovery.build("cloudidentity", "v1", cache_discovery=False)

    @property
    def source(self) -> str:
        return self._source

    def collect(self, execution_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
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
                member_email = str(m.get("preferredMemberKey", {}).get("id", "")).strip()
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
        # Cloud Identity query for Google Groups in the customer.
        query = (
            f"parent=='customers/{self._customer_id}'"
            " && 'cloudidentity.googleapis.com/groups.discussion_forum' in labels"
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
