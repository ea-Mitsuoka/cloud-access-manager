from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AccessRequest:
    """
    アクセスリクエストを表すデータクラス。

    Attributes:
        request_id (str): リクエストの一意なID。
        request_type (str): リクエストの種類 (例: "GRANT")。
        principal_email (str): アクセスを要求するプリンシパルのメールアドレス。
        resource_name (str): アクセス対象のリソース名。
        role (str): 要求するIAMロール。
        status (str): リクエストの現在のステータス (例: "APPROVED")。
        approved_at (datetime | None): リクエストが承認された日時。
        reason (str | None): リクエストの理由。
    """

    request_id: str
    request_type: str
    principal_email: str
    resource_name: str
    role: str
    status: str
    approved_at: datetime | None
    reason: str | None


@dataclass(frozen=True)
class ExpiredAccessRequest(AccessRequest):
    """
    期限切れのアクセスリクエストを表すデータクラス。

    Attributes:
        expires_at (datetime | None): アクセス権が失効する日時。
        is_permission_active (bool): 現在、この権限が有効かどうかを示すフラグ。
    """

    expires_at: datetime | None
    is_permission_active: bool


@dataclass(frozen=True)
class ExecutionResult:
    """
    IAMポリシー変更の実行結果を表すデータクラス。

    Attributes:
        result (str): 実行結果 ("SUCCESS", "FAILED", "SKIPPED")。
        action (str): 実行されたアクション (例: "GRANT", "REVOKE")。
        target (str): アクションの対象となったリソース。
        before_hash (str | None): 変更前のIAMポリシーのハッシュ。
        after_hash (str | None): 変更後のIAMポリシーのハッシュ。
        error_code (str | None): エラーが発生した場合のエラーコード。
        error_message (str | None): エラーが発生した場合のエラーメッセージ。
        details (dict[str, Any] | None): その他の詳細情報。
    """

    result: str  # SUCCESS / FAILED / SKIPPED
    action: str
    target: str
    before_hash: str | None
    after_hash: str | None
    error_code: str | None = None
    error_message: str | None = None
    details: dict[str, Any] | None = None
