from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from googleapiclient import discovery
from googleapiclient.errors import HttpError

from .models import AccessRequest, ExecutionResult

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.5


class IamExecutor:
    """IAMポリシーの変更を実際に実行するクラス。"""

    def __init__(self) -> None:
        """IamExecutorを初期化します。"""
        self._local = threading.local()

    @property
    def _crm(self):
        if not hasattr(self._local, "crm"):
            self._local.crm = discovery.build(
                "cloudresourcemanager",
                "v3",
                cache_discovery=False,
            )
        return self._local.crm

    def execute(self, req: AccessRequest) -> ExecutionResult:
        """
        アクセスリクエストに基づいてIAMポリシーの変更を実行します。

        Args:
            req (AccessRequest): 実行するアクセスリクエスト。

        Returns:
            ExecutionResult: 実行結果。

        Raises:
            HttpError: IAM APIの呼び出しでリトライ不可能なエラーが発生した場合。
        """
        action = self._normalize_action(req.request_type)
        member = self._to_member(req.principal_email)

        for i in range(MAX_RETRIES):
            try:
                policy = self._get_policy(req.resource_name)
                before_hash = self._policy_hash(policy)
                original_policy_for_diff = json.loads(json.dumps(policy))

                changed = self._apply_diff(
                    original_policy_for_diff, req.role, member, action
                )

                if not changed:
                    return ExecutionResult(
                        result="SKIPPED",
                        action=action,
                        target=req.resource_name,
                        before_hash=before_hash,
                        after_hash=before_hash,
                        details={"reason": "no diff"},
                    )

                # The policy to set must include the original etag.
                updated_policy_to_set = original_policy_for_diff
                updated_policy_to_set["etag"] = policy["etag"]

                updated = self._set_policy(req.resource_name, updated_policy_to_set)
                after_hash = self._policy_hash(updated)
                return ExecutionResult(
                    result="SUCCESS",
                    action=action,
                    target=req.resource_name,
                    before_hash=before_hash,
                    after_hash=after_hash,
                )

            except HttpError as e:
                if e.resp.status == 409:  # Conflict
                    if i < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF_SECONDS * (i + 1))
                        continue  # Retry
                raise  # Re-raise other HttpErrors or on last retry

        # This part should not be reached if retries are exhausted and the last error was re-raised.
        # But as a fallback, return a failure.
        return ExecutionResult(  # pragma: no cover
            result="FAILED",
            action=action,
            target=req.resource_name,
            before_hash=None,
            after_hash=None,
            error_code="CONFLICT_RETRIES_EXHAUSTED",
            error_message=(
                f"Failed to apply IAM policy after {MAX_RETRIES} attempts "
                f"due to conflicts."
            ),
        )

    @staticmethod
    def _normalize_action(request_type: str) -> str:
        """
        リクエストタイプを正規化されたアクション文字列（GRANT/REVOKE）に変換します。

        Args:
            request_type (str): "GRANT" または "REVOKE"。大文字小文字は区別しません。

        Returns:
            str: "GRANT" または "REVOKE"。
        """
        upper = request_type.upper()
        if upper == "REVOKE":
            return "REVOKE"
        return "GRANT"

    @staticmethod
    def _to_member(principal_email: str) -> str:
        """
        プリンシパルのメールアドレスをIAMポリシーのメンバー形式に変換します。

        Args:
            principal_email (str): ユーザーまたはサービスアカウントのメールアドレス。

        Returns:
            str: IAMポリシーで使用されるメンバー文字列 (例: "user:foo@example.com")。
        """
        if ":" in principal_email:
            return principal_email
        if principal_email.endswith("gserviceaccount.com"):
            return f"serviceAccount:{principal_email}"
        return f"user:{principal_email}"

    @staticmethod
    def _parse_resource(resource_name: str) -> tuple[str, str]:
        """
        リソース名をリソースタイプとIDに分割します。

        Args:
            resource_name (str): 完全なリソース名 (例: "projects/my-project")。

        Returns:
            tuple[str, str]: リソースタイプとリソースIDのタプル。

        Raises:
            ValueError: サポートされていないリソース名形式の場合。
        """
        if resource_name.startswith("projects/"):
            return "projects", resource_name.split("/", 1)[1]
        raise ValueError(f"unsupported resource_name format (only projects are allowed): {resource_name}")

    def _get_policy(self, resource: str) -> dict[str, Any]:
        """
        指定されたリソースのIAMポリシーを取得します。
        ※既存の条件付きバインディング（IAM Condition）の消失を防ぐため、必ず Policy Version 3 を指定します。

        Args:
            resource (str): ポリシーを取得するリソースの完全な名前。

        Returns:
            dict[str, Any]: IAMポリシー。

        Raises:
            ValueError: サポートされていないリソースタイプの場合。
        """
        body = {"options": {"requestedPolicyVersion": 3}}
        if resource.startswith("projects/"):
            return (
                self._crm.projects()
                .getIamPolicy(resource=resource, body=body)
                .execute()
            )

        else:
            raise ValueError(
                "Unsupported resource type for getIamPolicy: {}".format(resource)
            )

    def _set_policy(self, resource: str, policy: dict[str, Any]) -> dict[str, Any]:
        """
        指定されたリソースにIAMポリシーを設定します。

        Args:
            resource (str): ポリシーを設定するリソースの完全な名前。
            policy (dict[str, Any]): 設定するIAMポリシー。

        Returns:
            dict[str, Any]: 更新されたIAMポリシー。

        Raises:
            ValueError: サポートされていないリソースタイプの場合。
        """
        body = {"policy": policy}
        if resource.startswith("projects/"):
            return (
                self._crm.projects()
                .setIamPolicy(resource=resource, body=body)
                .execute()
            )

        else:
            raise ValueError(
                "Unsupported resource type for setIamPolicy: {}".format(resource)
            )

    @staticmethod
    def _policy_hash(policy: dict[str, Any]) -> str:
        """
        IAMポリシーのSHA256ハッシュを計算します。

        Args:
            policy (dict[str, Any]): ハッシュを計算するIAMポリシー。

        Returns:
            str: ポリシーのSHA256ハッシュ（16進数文字列）。
        """
        payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _apply_diff(
        policy: dict[str, Any], role: str, member: str, action: str
    ) -> bool:
        """
        IAMポリシーの辞書にインプレースで変更を適用します。

        Args:
            policy (dict[str, Any]): 変更を適用するIAMポリシーの辞書。
            role (str): 対象のロール。
            member (str): 対象のメンバー。
            action (str): "GRANT" または "REVOKE"。

        Returns:
            bool: ポリシーが実際に変更された場合はTrue、変更がなかった場合はFalse。
        """
        bindings = policy.setdefault("bindings", [])
        changed = False

        if action == "GRANT":
            role_binding = None
            for binding in bindings:
                # 既存の条件付きバインディング（IAM Condition）への誤爆付与を防ぐため、条件なしのものを探す
                if binding.get("role") == role and "condition" not in binding:
                    role_binding = binding
                    break

            if role_binding is None:
                bindings.append({"role": role, "members": [member]})
                return True

            members = role_binding.setdefault("members", [])
            if member not in members:
                role_binding["members"].append(member)
                return True
            return False

        if action == "REVOKE":
            new_bindings = []
            for binding in bindings:
                # 条件付き/条件なしに関わらず、すべての該当ロールからメンバーを確実に剥奪する
                if binding.get("role") == role:
                    members = binding.get("members", [])
                    if member in members:
                        members.remove(member)
                        changed = True
                    if members:  # メンバーが空でなければバインディングを残す
                        binding["members"] = members
                        new_bindings.append(binding)
                else:
                    new_bindings.append(binding)

            if changed:
                policy["bindings"] = new_bindings
            return changed

        return False
