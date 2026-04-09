from __future__ import annotations

import logging
from typing import Any

from googleapiclient import discovery


class PrincipalCollector:
    def __init__(
        self, workspace_customer_id: str, target_project_id: str, target_org_id: str
    ) -> None:
        self._customer_id = workspace_customer_id or "my_customer"
        self._target_project_id = target_project_id
        self._target_org_id = target_org_id
        self._cloudidentity_api = discovery.build(
            "cloudidentity", "v1", cache_discovery=False
        )
        self._admin_api = discovery.build(
            "admin", "directory_v1", cache_discovery=False
        )
        self._iam_api = discovery.build("iam", "v1", cache_discovery=False)

    def collect(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, int],
        list[dict[str, str]],
    ]:
        principals = []
        memberships = []
        counts = {"Group": 0, "GroupMembership": 0, "User": 0, "ServiceAccount": 0}
        warnings: list[dict[str, str]] = []

        try:
            query = f"parent=='customers/{self._customer_id}' && 'cloudidentity.googleapis.com/groups.discussion_forum' in labels"  # noqa: E501
            page_token = ""
            while True:
                resp = (
                    self._cloudidentity_api.groups()
                    .search(query=query, pageSize=200, pageToken=page_token)
                    .execute()
                )  # noqa: E501
                for g in resp.get("groups", []):
                    email = str(g.get("groupKey", {}).get("id", "")).strip()
                    name = str(g.get("displayName", "")).strip()
                    group_name = str(g.get("name", "")).strip()
                    if email:
                        principals.append(
                            {
                                "principal_email": email,
                                "principal_name": name,
                                "principal_type": "GROUP",
                            }
                        )  # noqa: E501
                        counts["Group"] += 1
                        if group_name:
                            try:
                                member_page_token = ""
                                while True:
                                    member_resp = (
                                        self._cloudidentity_api.groups()
                                        .memberships()
                                        .list(
                                            parent=group_name,
                                            pageSize=200,
                                            pageToken=member_page_token,
                                            view="FULL",
                                        )
                                        .execute()
                                    )
                                    for m in member_resp.get("memberships", []):
                                        member_email = str(
                                            m.get("preferredMemberKey", {}).get(
                                                "id", ""
                                            )
                                        ).strip()
                                        if not member_email:
                                            continue
                                        role_name = ""
                                        roles = m.get("roles", [])
                                        if roles:
                                            role_name = str(
                                                roles[0].get("name", "")
                                            ).strip()
                                        memberships.append(
                                            {
                                                "group_email": email,
                                                "member_email": member_email,
                                                "member_display_name": None,
                                                "membership_type": role_name or None,
                                                "source": "cloudidentity",
                                            }
                                        )
                                        counts["GroupMembership"] += 1
                                    member_page_token = str(
                                        member_resp.get("nextPageToken", "")
                                    ).strip()
                                    if not member_page_token:
                                        break
                            except Exception as member_exc:
                                logging.warning(
                                    "Failed to collect memberships "
                                    f"for {email}: {member_exc}"
                                )
                                warnings.append(
                                    {
                                        "source": "CLOUD_IDENTITY_GROUP_MEMBERSHIPS",
                                        "error": f"{email}: {member_exc}",
                                    }
                                )
                page_token = str(resp.get("nextPageToken", "")).strip()
                if not page_token:
                    break
        except Exception as e:
            logging.warning(f"Failed to collect groups: {e}")
            warnings.append({"source": "CLOUD_IDENTITY_GROUPS", "error": str(e)})

        try:
            page_token = None
            while True:
                resp = (
                    self._admin_api.users()
                    .list(
                        customer=self._customer_id, maxResults=200, pageToken=page_token
                    )
                    .execute()
                )  # noqa: E501
                for u in resp.get("users", []):
                    email = str(u.get("primaryEmail", "")).strip()
                    name = str(u.get("name", {}).get("fullName", "")).strip()
                    if email:
                        principals.append(
                            {
                                "principal_email": email,
                                "principal_name": name,
                                "principal_type": "USER",
                            }
                        )  # noqa: E501
                        counts["User"] += 1
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except Exception as e:
            logging.warning(f"Failed to collect users: {e}")
            warnings.append({"source": "ADMIN_DIRECTORY_USERS", "error": str(e)})

        if self._target_project_id:
            try:
                page_token = None
                while True:
                    resp = (
                        self._iam_api.projects()
                        .serviceAccounts()
                        .list(
                            name=f"projects/{self._target_project_id}",
                            pageSize=100,
                            pageToken=page_token,
                        )
                        .execute()
                    )  # noqa: E501
                    for sa in resp.get("accounts", []):
                        email = str(sa.get("email", "")).strip()
                        name = str(sa.get("displayName", "")).strip()
                        if email:
                            principals.append(
                                {
                                    "principal_email": email,
                                    "principal_name": name,
                                    "principal_type": "SERVICE_ACCOUNT",
                                }
                            )  # noqa: E501
                            counts["ServiceAccount"] += 1
                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
            except Exception as e:
                logging.warning(f"Failed to collect service accounts: {e}")
                warnings.append({"source": "IAM_SERVICE_ACCOUNTS", "error": str(e)})

        return principals, memberships, counts, warnings
