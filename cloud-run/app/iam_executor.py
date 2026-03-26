from __future__ import annotations

import hashlib
import json
from typing import Any

from googleapiclient import discovery

from .models import AccessRequest, ExecutionResult


class IamExecutor:
    def __init__(self) -> None:
        self._crm = discovery.build(
            "cloudresourcemanager",
            "v3",
            cache_discovery=False,
        )

    def execute(self, req: AccessRequest) -> ExecutionResult:
        action = self._normalize_action(req.request_type)
        member = self._to_member(req.principal_email)
        target_type, _ = self._parse_resource(req.resource_name)

        policy = self._get_policy(req.resource_name)
        before_hash = self._policy_hash(policy)
        changed = self._apply_diff(policy, req.role, member, action)

        if not changed:
            return ExecutionResult(
                result="SKIPPED",
                action=action,
                target=req.resource_name,
                before_hash=before_hash,
                after_hash=before_hash,
                details={"reason": "no diff"},
            )

        updated = self._set_policy(req.resource_name, policy)
        after_hash = self._policy_hash(updated)
        return ExecutionResult(
            result="SUCCESS",
            action=action,
            target=req.resource_name,
            before_hash=before_hash,
            after_hash=after_hash,
        )

    @staticmethod
    def _normalize_action(request_type: str) -> str:
        upper = request_type.upper()
        if upper == "REVOKE":
            return "REVOKE"
        return "GRANT"

    @staticmethod
    def _to_member(principal_email: str) -> str:
        if ":" in principal_email:
            return principal_email
        if principal_email.endswith("gserviceaccount.com"):
            return f"serviceAccount:{principal_email}"
        return f"user:{principal_email}"

    @staticmethod
    def _parse_resource(resource_name: str) -> tuple[str, str]:
        if resource_name.startswith("projects/"):
            return "projects", resource_name.split("/", 1)[1]
        if resource_name.startswith("folders/"):
            return "folders", resource_name.split("/", 1)[1]
        if resource_name.startswith("organizations/"):
            return "organizations", resource_name.split("/", 1)[1]
        raise ValueError(
            f"unsupported resource_name format: {resource_name}"
        )

    def _get_policy(self, resource: str) -> dict[str, Any]:
        if resource.startswith("projects/"):
            return (
                self._crm.projects().getIamPolicy(resource=resource).execute()
            )
        elif resource.startswith("folders/"):
            return (
                self._crm.folders()
                .getIamPolicy(resource=resource)
                .execute()
            )
        elif resource.startswith("organizations/"):
            return (
                self._crm.organizations()
                .getIamPolicy(resource=resource)
                .execute()
            )
        else:
            raise ValueError(
                "Unsupported resource type for getIamPolicy: {}".format(
                    resource
                )
            )

    def _set_policy(
        self, resource: str, policy: dict[str, Any]
    ) -> dict[str, Any]:
        body = {"policy": policy}
        if resource.startswith("projects/"):
            return (
                self._crm.projects()
                .setIamPolicy(resource=resource, body=body)
                .execute()
            )
        elif resource.startswith("folders/"):
            return (
                self._crm.folders()
                .setIamPolicy(resource=resource, body=body)
                .execute()
            )
        elif resource.startswith("organizations/"):
            return (
                self._crm.organizations()
                .setIamPolicy(resource=resource, body=body)
                .execute()
            )
        else:
            raise ValueError(
                "Unsupported resource type for setIamPolicy: {}".format(
                    resource
                )
            )

    @staticmethod
    def _policy_hash(policy: dict[str, Any]) -> str:
        payload = json.dumps(
            policy, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _apply_diff(
        policy: dict[str, Any], role: str, member: str, action: str
    ) -> bool:
        bindings = policy.setdefault("bindings", [])
        role_binding = None
        for binding in bindings:
            if binding.get("role") == role:
                role_binding = binding
                break

        if action == "GRANT":
            if role_binding is None:
                bindings.append({"role": role, "members": [member]})
                return True
            members = set(role_binding.setdefault("members", []))
            if member in members:
                return False
            role_binding["members"].append(member)
            return True

        if role_binding is None:
            return False

        members = role_binding.setdefault("members", [])
        if member not in members:
            return False

        role_binding["members"] = [m for m in members if m != member]
        if not role_binding["members"]:
            policy["bindings"] = [b for b in bindings if b.get("role") != role]
        return True
