from __future__ import annotations

import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from dataclasses import replace
from typing import Any
from functools import wraps

from flask import Flask, jsonify, request, render_template
from google.api_core.exceptions import PermissionDenied as GcpPermissionDenied
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from googleapiclient.errors import HttpError

from .iam_executor import IamExecutor
from .models import ExecutionResult
from .iam_policy_collector import IamPolicyCollector
from .principal_collector import PrincipalCollector
from .resource_inventory_collector import ResourceInventoryCollector
from .repository import Repository
from .scope_validator import ScopeConfig, ScopeValidator
from .ai_advisor import suggest_iam_roles, validate_role_with_ai

app = Flask(__name__, template_folder="templates")

# Set up basic logging
logging.basicConfig(level=logging.INFO)

PROJECT_ID = os.environ["BQ_PROJECT_ID"]
DATASET_ID = os.environ["BQ_DATASET_ID"]
EXECUTOR_IDENTITY = os.environ.get("EXECUTOR_IDENTITY", "cloud-run")
GAS_INVOKER_EMAIL = os.environ.get("GAS_INVOKER_EMAIL", "").strip()
TARGET_PROJECT_ID = os.environ.get("MGMT_TARGET_PROJECT_ID", "").strip()
TARGET_ORG_ID = os.environ.get("MGMT_TARGET_ORGANIZATION_ID", "").strip()
WORKSPACE_CUSTOMER_ID = os.environ.get("WORKSPACE_CUSTOMER_ID", "my_customer").strip()
SCHEDULER_INVOKER_EMAIL = os.environ.get("SCHEDULER_INVOKER_EMAIL", "").strip()
IAP_OAUTH_CLIENT_ID = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()

repo = Repository(project_id=PROJECT_ID, dataset_id=DATASET_ID)
iam_executor = IamExecutor()
scope_validator = ScopeValidator(
    ScopeConfig(
        target_project_id=TARGET_PROJECT_ID,
        target_org_id=TARGET_ORG_ID,
    )
)
resource_collector = ResourceInventoryCollector(
    target_project_id=TARGET_PROJECT_ID,
    target_org_id=TARGET_ORG_ID,
)
principal_collector = PrincipalCollector(
    workspace_customer_id=WORKSPACE_CUSTOMER_ID,
    target_project_id=TARGET_PROJECT_ID,
    target_org_id=TARGET_ORG_ID,
)
iam_policy_collector = IamPolicyCollector(
    target_project_id=TARGET_PROJECT_ID,
    target_org_id=TARGET_ORG_ID,
)

# --- Authorization Decorators ---


def require_oidc_auth(f):
    """Cloud Scheduler または GAS からの機械的な OIDC トークン通信を検証するデコレータ。"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _authorize():
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)

    return decorated_function


def require_iap_auth(f):
    """IAPを通過した人間（ブラウザ）からのアクセスを検証するデコレータ。"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        iap_email = request.headers.get("X-Goog-Authenticated-User-Email", "")
        if not iap_email:
            # ローカル開発時のフォールバック (IAP無効時)
            if not IAP_OAUTH_CLIENT_ID:
                request.environ["user_email"] = "local-dev@example.com"
                return f(*args, **kwargs)
            logging.warning("Blocked access without IAP header.")
            return "Unauthorized: Please access via IAP.", 401

        # ヘッダから "accounts.google.com:" プレフィックスを除去
        clean_email = iap_email.replace("accounts.google.com:", "").strip().lower()
        request.environ["user_email"] = clean_email
        return f(*args, **kwargs)

    return decorated_function


# --- Web Portal UI ---


@app.route("/", methods=["GET"])
@require_iap_auth
def index():
    """IAP経由でアクセスされるSaaSポータルのUIを提供します。"""
    email = request.environ.get("user_email", "unknown@example.com")
    initial_data = request.args.to_dict()
    return render_template(
        "RoleAdvisor.html", requester_email=email, initial_data=initial_data
    )


# --- Batch / System APIs (Protected by OIDC) ---


@app.get("/healthz")
def healthz():
    """ヘルスチェックエンドポイント。

    Returns:
        Response: 常に {"ok": True} を含むJSONレスポンス。
    """
    return jsonify({"ok": True})


@app.post("/execute")
@require_oidc_auth
def execute_request():
    """
    承認済みのアクセスリクエストに基づいてIAMポリシー変更を実行します。

    Returns:
        Response: 実行結果を含むJSONレスポンス。
    """
    payload = request.get_json(silent=True) or {}
    request_id = str(payload.get("request_id", "")).strip()
    if not request_id:
        return jsonify({"error": "request_id is required"}), 400

    result_payload, http_status = _execute_request_by_id(request_id)
    return jsonify(result_payload), http_status


def _execute_request_by_id(request_id: str) -> tuple[dict[str, Any], int]:
    """単一リクエストのIAM反映を実行し、レスポンス本体とHTTPステータスを返します。"""
    execution_id = str(uuid.uuid4())

    req = repo.get_approved_request(request_id)
    if req is None:
        return {"error": f"request_id not found: {request_id}"}, 404

    if req.status != "APPROVED":
        result = ExecutionResult(
            result="SKIPPED",
            action="GRANT" if req.request_type != "REVOKE" else "REVOKE",
            target=req.resource_name,
            before_hash=None,
            after_hash=None,
            details={"reason": f"status is {req.status}"},
        )
        repo.insert_change_log(execution_id, request_id, EXECUTOR_IDENTITY, result)
        return (
            {
                "execution_id": execution_id,
                "request_id": request_id,
                "result": result.result,
                "reason": "status_not_approved",
            },
            200,
        )

    scope_error = scope_validator.validate_resource_name(req.resource_name)
    if scope_error:
        result = ExecutionResult(
            result="FAILED",
            action="GRANT" if req.request_type != "REVOKE" else "REVOKE",
            target=req.resource_name,
            before_hash=None,
            after_hash=None,
            error_code="OUT_OF_SCOPE",
            error_message=scope_error,
        )
        repo.insert_change_log(execution_id, request_id, EXECUTOR_IDENTITY, result)
        return (
            {
                "execution_id": execution_id,
                "request_id": request_id,
                "result": result.result,
                "error_code": result.error_code,
                "error_message": result.error_message,
            },
            400,
        )

    if repo.has_success_execution(request_id):
        result = ExecutionResult(
            result="SKIPPED",
            action="GRANT" if req.request_type != "REVOKE" else "REVOKE",
            target=req.resource_name,
            before_hash=None,
            after_hash=None,
            details={"reason": "already executed"},
        )
        repo.insert_change_log(execution_id, request_id, EXECUTOR_IDENTITY, result)
        return (
            {
                "execution_id": execution_id,
                "request_id": request_id,
                "result": result.result,
                "reason": "idempotent_skip",
            },
            200,
        )

    if "[緊急]" in (req.reason or ""):
        logging.warning(
            f"[BREAK-GLASS] Emergency access execution triggered! "
            f"Principal: {req.principal_email}, Role: {req.role}, Resource: {req.resource_name}, Reason: {req.reason}"
        )

    try:
        result = iam_executor.execute(req)
    except Exception as exc:  # pragma: no cover
        logging.error(
            f"Execution failed for request {request_id}: {exc}", exc_info=True
        )
        result = ExecutionResult(
            result="FAILED",
            action="GRANT" if req.request_type != "REVOKE" else "REVOKE",
            target=req.resource_name,
            before_hash=None,
            after_hash=None,
            error_code=type(exc).__name__,
            error_message=str(exc),
            details={"trace": traceback.format_exc(limit=3)},
        )

    repo.insert_change_log(execution_id, request_id, EXECUTOR_IDENTITY, result)

    http_status = 200 if result.result in ("SUCCESS", "SKIPPED") else 500
    return (
        {
            "execution_id": execution_id,
            "request_id": request_id,
            "result": result.result,
            "error_code": result.error_code,
            "error_message": result.error_message,
        },
        http_status,
    )


@app.post("/collect/resources")
@require_oidc_auth
def collect_resources():
    """
    管理対象スコープ内のGCPリソースを収集し、棚卸しデータをDBに保存します。

    Returns:
        Response: 収集結果を含むJSONレスポンス。
    """
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())

    try:
        rows, counts, scope = resource_collector.collect_rows(execution_id=execution_id)
        inserted = repo.insert_resource_inventory_rows(rows)
        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type="RESOURCE_COLLECTION",
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts={"inserted_rows": inserted, **counts},
            details={"scope": scope},
        )
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type="RESOURCE_COLLECTION",
            execution_id=execution_id,
            exc=exc,
        )
        report_for_db = {}
        for k, v in report.items():
            if k != "http_status":
                report_for_db[k] = v
        repo.insert_pipeline_job_report(**report_for_db)
        json_response = {
            "execution_id": execution_id,
            "result": report["result"],
            "error_code": (report["error_code"]),
            "error_message": (report["error_message"]),
            "hint": report["hint"],
        }
        return jsonify(json_response), report["http_status"]

    return jsonify(
        {
            "execution_id": execution_id,
            "result": "SUCCESS",
            "scope": scope,
            "inserted_rows": inserted,
            "counts": counts,
        }
    )


@app.post("/collect/principals")
@require_oidc_auth
def collect_principals():
    """各種APIからプリンシパル（User, Group, SA）を収集し、マスタを更新します。"""
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())

    try:
        principals, memberships, counts, warnings = principal_collector.collect()
        upserted = repo.upsert_principal_catalog(
            principals, deactivate_missing=(len(warnings) == 0)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        for row in memberships:
            row["execution_id"] = execution_id
            row["assessed_at"] = now_iso
        memberships_inserted = repo.insert_group_membership_rows(memberships)
        is_partial = len(warnings) > 0
        result = "PARTIAL_SUCCESS" if is_partial else "SUCCESS"
        error_code = "PARTIAL_COLLECTION" if is_partial else None
        error_message = (
            "One or more principal sources could not be collected. "
            "See details.warnings for source-level errors."
            if is_partial
            else None
        )
        hint = (
            "Verify Admin SDK / Cloud Identity / IAM permissions and enabled APIs."
            if is_partial
            else None
        )
        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type="PRINCIPAL_COLLECTION",
            result=result,
            error_code=error_code,
            error_message=error_message,
            hint=hint,
            counts={
                "upserted_rows": upserted,
                "upserted_principals": upserted,
                "inserted_memberships": memberships_inserted,
                **counts,
            },
            details={
                "note": "Collected from Workspace and IAM",
                "warnings": warnings,
            },
        )
        return jsonify(
            {
                "execution_id": execution_id,
                "result": result,
                "upserted_rows": upserted,
                "upserted_principals": upserted,
                "inserted_memberships": memberships_inserted,
                "counts": counts,
                "warnings": warnings,
            }
        )
    except Exception as exc:  # pragma: no cover
        logging.error(f"Principal collection failed: {exc}", exc_info=True)
        report = _build_collection_error_report(
            job_type="PRINCIPAL_COLLECTION", execution_id=execution_id, exc=exc
        )
        report_for_db = {k: v for k, v in report.items() if k != "http_status"}
        repo.insert_pipeline_job_report(**report_for_db)
        return (
            jsonify(
                {
                    "execution_id": execution_id,
                    "result": report["result"],
                    "error_code": report["error_code"],
                    "error_message": report["error_message"],
                    "hint": report["hint"],
                }
            ),
            report["http_status"],
        )


@app.post("/collect/iam-policies")
@require_oidc_auth
def collect_iam_policies():
    """管理対象スコープ内のIAMポリシーを収集し、DBを洗い替えます。"""
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())

    try:
        rows, counts, scope = iam_policy_collector.collect_rows(
            execution_id=execution_id
        )
        inserted = repo.replace_iam_policy_permissions(rows)
        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type="IAM_POLICY_COLLECTION",
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts={"inserted_rows": inserted, **counts},
            details={"scope": scope},
        )
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type="IAM_POLICY_COLLECTION", execution_id=execution_id, exc=exc
        )
        report_for_db = {k: v for k, v in report.items() if k != "http_status"}
        repo.insert_pipeline_job_report(**report_for_db)
        return (
            jsonify(
                {
                    "execution_id": execution_id,
                    "result": report["result"],
                    "error_code": report["error_code"],
                    "error_message": report["error_message"],
                    "hint": report["hint"],
                }
            ),
            report["http_status"],
        )

    return jsonify(
        {
            "execution_id": execution_id,
            "result": "SUCCESS",
            "scope": scope,
            "inserted_rows": inserted,
            "counts": counts,
        }
    )


@app.post("/reconcile")
@require_oidc_auth
def reconcile_iam_issues():
    """
    IAMの矛盾を検出し、issuesテーブルに記録するリコンシリエーションジョブを実行します。

    Returns:
        Response: 実行結果を含むJSONレスポンス。
    """
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())
    job_type = "IAM_RECONCILIATION"

    try:
        inserted_rows = repo.run_reconciliation_job()

        if inserted_rows > 0:
            logging.warning(
                f"[RECONCILIATION_ISSUE_DETECTED] Found {inserted_rows} IAM reconciliation issues. "
                "System detected unmanaged IAM bindings or application failures."
            )

        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type=job_type,
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts={"inserted_issues": inserted_rows},
            details={"sql_file": "003_reconciliation.sql"},
        )
        return jsonify({"execution_id": execution_id, "result": "SUCCESS"})
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type=job_type, execution_id=execution_id, exc=exc
        )
        report_for_db = {}
        for k, v in report.items():
            if k != "http_status":
                report_for_db[k] = v
        repo.insert_pipeline_job_report(**report_for_db)
        json_response = {
            "execution_id": execution_id,
            "result": report["result"],
            "error_code": (report["error_code"]),
            "error_message": (report["error_message"]),
            "hint": report["hint"],
        }
        return jsonify(json_response), report["http_status"]


@app.post("/revoke_expired_permissions")
@require_oidc_auth
def revoke_expired_permissions():
    """
    期限切れの承認済みアクセス権限を自動的に取り消します。

    Returns:
        Response: 実行結果（取り消し、スキップ、失敗の件数）を含むJSONレスポンス。
    """
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())
    job_type = "EXPIRED_PERMISSION_REVOCATION"

    try:
        expired_requests = repo.search_expired_approved_access_requests()
        revoked_count = 0
        skipped_count = 0
        failed_count = 0

        updates_for_db = []
        for req in expired_requests:
            if not req.is_permission_active:
                result = ExecutionResult(
                    result="SKIPPED",
                    action="REVOKE",
                    target=req.resource_name,
                    before_hash=None,
                    after_hash=None,
                    details={"reason": "Already gone"},
                )
                repo.insert_change_log(
                    execution_id, req.request_id, EXECUTOR_IDENTITY, result
                )
                updates_for_db.append(
                    {"request_id": req.request_id, "status": "REVOKED_ALREADY_GONE"}
                )
                skipped_count += 1
                continue

            try:
                req_to_revoke = replace(req, request_type="REVOKE")
                result = iam_executor.execute(req_to_revoke)
                repo.insert_change_log(
                    execution_id, req.request_id, EXECUTOR_IDENTITY, result
                )

                if result.result == "SUCCESS":
                    updates_for_db.append(
                        {"request_id": req.request_id, "status": "REVOKED"}
                    )
                    revoked_count += 1
                elif result.result == "SKIPPED":
                    updates_for_db.append(
                        {"request_id": req.request_id, "status": "REVOKED_ALREADY_GONE"}
                    )
                    skipped_count += 1
                else:
                    updates_for_db.append(
                        {"request_id": req.request_id, "status": "REVOKE_FAILED"}
                    )
                    failed_count += 1
            except Exception as inner_exc:
                logging.error(
                    f"Failed to automatically revoke permission for request {req.request_id}: {inner_exc}",
                    exc_info=True,
                )
                result = ExecutionResult(
                    result="FAILED",
                    action="REVOKE",
                    target=req.resource_name,
                    before_hash=None,
                    after_hash=None,
                    error_code=type(inner_exc).__name__,
                    error_message=str(inner_exc),
                    details={"trace": traceback.format_exc(limit=3)},
                )
                repo.insert_change_log(
                    execution_id, req.request_id, EXECUTOR_IDENTITY, result
                )
                updates_for_db.append(
                    {"request_id": req.request_id, "status": "REVOKE_FAILED"}
                )
                failed_count += 1

        if updates_for_db:
            repo.bulk_update_request_status_and_history_secure(
                updates=updates_for_db,
                actor_email="SYSTEM_AUTO_REVOKE",
                actor_source="SYSTEM_BATCH",
            )

        report_result = "SUCCESS" if failed_count == 0 else "FAILED"
        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type=job_type,
            result=report_result,
            error_code=None,
            error_message=None,
            hint=None,
            counts={
                "revoked": revoked_count,
                "skipped": skipped_count,
                "failed": failed_count,
            },
            details={},
        )
        return jsonify(
            {
                "execution_id": execution_id,
                "result": report_result,
                "revoked": revoked_count,
                "skipped": skipped_count,
                "failed": failed_count,
            }
        )
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type=job_type, execution_id=execution_id, exc=exc
        )
        report_for_db = {}
        for k, v in report.items():
            if k != "http_status":
                report_for_db[k] = v
        repo.insert_pipeline_job_report(**report_for_db)
        json_response = {
            "execution_id": execution_id,
            "result": report["result"],
            "error_code": (report["error_code"]),
            "error_message": (report["error_message"]),
            "hint": report["hint"],
        }
        return jsonify(json_response), report["http_status"]


@app.post("/jobs/update-iam-bindings-history")
@require_oidc_auth
def update_iam_bindings_history():
    """
    現在のIAMバインディングのスナップショットを履歴テーブルに保存するジョブを実行します。

    Returns:
        Response: 実行結果（挿入された行数）を含むJSONレスポンス。
    """
    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())
    job_type = "IAM_BINDINGS_HISTORY_UPDATE"

    try:
        # 1. プリンシパルマスタの同期

        # 2. 生のIAM履歴 (Raw History) の追記
        raw_inserted = repo.run_update_raw_bindings_history_job(execution_id)

        # 3. 帳票用整形済み履歴の追記
        inserted_rows = repo.run_update_bindings_history_job(execution_id)

        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type=job_type,
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts={"inserted_rows": inserted_rows, "raw_inserted_rows": raw_inserted},
            details={"note": "Includes principal catalog sync and raw history update"},
        )
        return jsonify(
            {
                "execution_id": execution_id,
                "result": "SUCCESS",
                "inserted_rows": inserted_rows,
                "raw_inserted_rows": raw_inserted,
            }
        )
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type=job_type, execution_id=execution_id, exc=exc
        )
        report_for_db = {}
        for k, v in report.items():
            if k != "http_status":
                report_for_db[k] = v
        repo.insert_pipeline_job_report(**report_for_db)
        json_response = {
            "execution_id": execution_id,
            "result": report["result"],
            "error_code": (report["error_code"]),
            "error_message": (report["error_message"]),
            "hint": report["hint"],
        }
        return jsonify(json_response), report["http_status"]


@app.get("/api/statuses")
@require_oidc_auth
def api_get_statuses():
    """GAS等のクライアント向けにステータスマスタの対応表を提供します。"""
    try:
        mapping = repo.get_status_master()
        # 英語のステータスコード自身もマッピングに含める（例: "APPROVED": "APPROVED"）
        for code in list(mapping.values()):
            if code:
                mapping[code] = code
        return jsonify({"mapping": mapping})
    except Exception as exc:
        logging.error(f"Failed to get statuses: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/requests")
@require_oidc_auth
def api_create_request():
    """新規アクセスリクエストを登録します。"""
    payload = request.get_json(silent=True) or {}
    try:
        repo.insert_access_request_raw(payload)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to create request: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/requests/bulk")
@require_oidc_auth
def api_create_requests_bulk():
    """新規アクセスリクエストを一括登録します。"""
    payload = request.get_json(silent=True) or {}
    requests_list = payload.get("requests", [])
    if not isinstance(requests_list, list):
        return jsonify({"error": "requests must be an array"}), 400
    if not requests_list:
        return jsonify({"result": "SUCCESS", "inserted_count": 0})
    try:
        repo.insert_access_requests_raw_bulk(requests_list)
        return jsonify({"result": "SUCCESS", "inserted_count": len(requests_list)})
    except Exception as exc:
        logging.error(f"Failed to bulk create requests: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/requests/bulk-status")
@require_oidc_auth
def api_bulk_update_request_status():
    """複数のアクセスリクエストのステータスを一括更新し、履歴を記録します。"""
    payload = request.get_json(silent=True) or {}
    updates = payload.get("updates", [])
    actor_email = payload.get("actor_email", "system")

    if not updates:
        return jsonify({"result": "SUCCESS", "updated_count": 0})

    for u in updates:
        s = str(u.get("status", "")).strip().upper()
        if s and s not in {"PENDING", "APPROVED", "REJECTED", "CANCELLED"}:
            return jsonify({"error": f"invalid status: {s}"}), 400

    try:
        detail = repo.bulk_update_request_status_and_history_detailed(
            updates=updates, actor_email=actor_email, actor_source="SHEET_EDIT_BULK"
        )
        return jsonify(
            {
                "result": "SUCCESS",
                "updated_count": len(detail["updated"]),
                "updated": detail["updated"],
                "skipped": detail["skipped"],
                "errors": detail["errors"],
            }
        )
    except Exception as exc:
        logging.error(f"Failed to bulk update status: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/v1/requests/bulk-review")
@require_oidc_auth
def api_bulk_review_requests():
    """レビュー結果を一括適用し、承認分はIAM反映まで行います。"""
    payload = request.get_json(silent=True) or {}
    reviews = payload.get("reviews", payload.get("updates", []))
    actor_email = str(payload.get("actor_email", "system"))
    if not isinstance(reviews, list):
        return jsonify({"error": "reviews must be an array"}), 400
    if not reviews:
        return jsonify(
            {"result": "SUCCESS", "requested_count": 0, "succeeded": [], "failed": []}
        )

    status_map = {
        "申請中": "PENDING",
        "承認済": "APPROVED",
        "却下": "REJECTED",
        "取消": "CANCELLED",
    }
    normalized_reviews: list[dict[str, Any]] = []
    reject_reason_map: dict[str, str] = {}
    for row in reviews:
        if not isinstance(row, dict):
            continue
        request_id = str(row.get("request_id", "")).strip()
        status_raw = str(row.get("status", "")).strip()
        status = status_map.get(status_raw, status_raw.upper())
        if status not in {"PENDING", "APPROVED", "REJECTED", "CANCELLED"}:
            return jsonify({"error": f"invalid status: {status_raw}"}), 400

        reject_reason = str(row.get("reject_reason", "")).strip()
        if request_id:
            reject_reason_map[request_id] = reject_reason
        normalized_reviews.append(
            {
                "request_id": request_id,
                "status": status,
                "reject_reason": reject_reason,
            }
        )

    try:
        detail = repo.bulk_update_request_status_and_history_detailed(
            updates=normalized_reviews,
            actor_email=actor_email,
            actor_source="SHEET_BULK_REVIEW",
        )
    except Exception as exc:
        logging.error(
            f"Failed to apply bulk review status updates: {exc}", exc_info=True
        )
        return jsonify({"error": str(exc)}), 500

    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in detail["errors"]:
        failed.append(
            {
                "request_id": row.get("request_id", ""),
                "status": row.get("status", ""),
                "error_code": row.get("error_code", "STATUS_UPDATE_ERROR"),
                "error_message": row.get("error_message", "status update failed"),
            }
        )
    for row in detail["skipped"]:
        failed.append(
            {
                "request_id": row.get("request_id", ""),
                "status": row.get("status", ""),
                "error_code": "SKIPPED",
                "error_message": row.get("reason", "skipped"),
            }
        )

    for row in detail["updated"]:
        request_id = str(row.get("request_id", "")).strip()
        status = str(row.get("status", "")).strip()
        if not request_id:
            continue

        if status == "APPROVED":
            execution_payload, execution_http = _execute_request_by_id(request_id)
            if execution_http >= 300 or execution_payload.get("result") == "FAILED":
                failed.append(
                    {
                        "request_id": request_id,
                        "status": status,
                        "error_code": execution_payload.get(
                            "error_code", "EXECUTION_FAILED"
                        ),
                        "error_message": execution_payload.get(
                            "error_message",
                            execution_payload.get("error", "execution failed"),
                        ),
                    }
                )
                continue
            succeeded.append(
                {
                    "request_id": request_id,
                    "status": status,
                    "execution_result": execution_payload.get("result", ""),
                    "execution_id": execution_payload.get("execution_id", ""),
                }
            )
            continue

        success_item = {"request_id": request_id, "status": status}
        if status == "REJECTED":
            reason = reject_reason_map.get(request_id, "")
            if reason:
                success_item["reject_reason"] = reason
        succeeded.append(success_item)

    if failed and succeeded:
        result = "PARTIAL_SUCCESS"
    elif failed and not succeeded:
        result = "FAILED"
    else:
        result = "SUCCESS"

    return jsonify(
        {
            "result": result,
            "requested_count": len(normalized_reviews),
            "succeeded": succeeded,
            "failed": failed,
        }
    )


@app.put("/api/requests/<request_id>/status")
@require_oidc_auth
def api_update_request_status(request_id):
    """アクセスリクエストのステータスを更新します。"""
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not status:
        return jsonify({"error": "status is required"}), 400

    status = str(status).strip().upper()
    if status not in {"PENDING", "APPROVED", "REJECTED", "CANCELLED"}:
        return jsonify({"error": f"invalid status: {status}"}), 400

    try:
        repo.update_request_status(request_id, status)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to update request status: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/history")
@require_oidc_auth
def api_create_history():
    """リクエスト履歴イベントを登録します。"""
    payload = request.get_json(silent=True) or {}
    try:
        repo.insert_request_history_event(payload)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to create history: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/history/bulk")
@require_oidc_auth
def api_create_history_bulk():
    """リクエスト履歴イベントを一括登録します。"""
    payload = request.get_json(silent=True) or {}
    events = payload.get("events", [])
    if not isinstance(events, list):
        return jsonify({"error": "events must be an array"}), 400
    if not events:
        return jsonify({"result": "SUCCESS", "inserted_count": 0})
    try:
        repo.insert_request_history_events_bulk(events)
        return jsonify({"result": "SUCCESS", "inserted_count": len(events)})
    except Exception as exc:
        logging.error(f"Failed to create history in bulk: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


# --- Frontend App APIs (Protected by IAP) ---


@app.post("/api/ai/suggest")
@require_iap_auth
def api_ai_suggest():
    """SaaSポータル: AIにロール候補を提案させます。"""
    payload = request.get_json(silent=True) or {}
    goal = payload.get("goal")
    if not goal:
        return jsonify({"error": "goal is required"}), 400
    try:
        res = suggest_iam_roles(
            PROJECT_ID, goal, payload.get("resource", ""), payload.get("principal", "")
        )
        return jsonify(res)
    except Exception as exc:
        logging.error(f"AI Suggestion failed: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/ai/validate")
@require_iap_auth
def api_ai_validate():
    """SaaSポータル: AIにロール名の妥当性を検証させます。"""
    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    if not role:
        return jsonify({"error": "role is required"}), 400
    try:
        res = validate_role_with_ai(
            PROJECT_ID, role, payload.get("goal", ""), payload.get("resource", "")
        )
        return jsonify(res)
    except Exception as exc:
        logging.error(f"AI Validation failed: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


# --- Helpers ---


def _authorize() -> bool:
    """
    リクエストを認証します。
    Cloud Scheduler または GAS からの OIDC トークンを検証します。
    """
    if not SCHEDULER_INVOKER_EMAIL and not GAS_INVOKER_EMAIL:
        return False

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return False

    # Cloud Runコンテナ内部ではhttpとして扱われるため、Audience検証用にhttpsへ強制する。
    # IAP移行期は run.app audience と IAP OAuth client ID の両方を許容する。
    expected_audiences = [request.url_root.rstrip("/").replace("http://", "https://")]
    if IAP_OAUTH_CLIENT_ID:
        expected_audiences.append(IAP_OAUTH_CLIENT_ID)

    claims: dict[str, Any] | None = None
    last_error: Exception | None = None
    for expected_audience in expected_audiences:
        try:
            claims = google_id_token.verify_oauth2_token(
                token, google_auth_requests.Request(), expected_audience
            )
            break
        except Exception as e:
            last_error = e

    if claims is None:
        logging.warning(f"OIDC verification failed: {last_error}")
        return False

    email = str(claims.get("email", "")).strip().lower()
    allowed_emails = [
        e.lower() for e in (SCHEDULER_INVOKER_EMAIL, GAS_INVOKER_EMAIL) if e
    ]
    return email in allowed_emails


@app.post("/api/ui/requests/bulk")
@require_iap_auth
def api_ui_create_requests_bulk():
    """SaaSポータル(Web UI)からの一括申請を受け付け、DBへ保存します。"""
    payload = request.get_json(silent=True) or {}
    requests_data = payload.get("requests", [])
    request_group_id = payload.get("requestGroupId", str(uuid.uuid4()))
    requester_email = request.environ.get("user_email", "unknown@example.com")

    if not requests_data:
        return jsonify({"result": "SUCCESS", "inserted_count": 0})

    bq_requests = []
    history_events = []
    emergency_ids = []
    requested_at = datetime.now(timezone.utc).isoformat()

    for req in requests_data:
        role = str(req.get("role", "")).strip()
        if role and not role.startswith("roles/"):
            return jsonify({"error": f"Invalid role: {role}"}), 400

        raw_type = str(req.get("requestType", ""))
        is_emergency = "緊急" in raw_type or "EMERGENCY" in raw_type.upper()

        reason = str(req.get("reason", "")).strip()
        if is_emergency and not reason.startswith("[緊急]"):
            reason = f"[緊急] {reason}"

        expires_raw = str(req.get("expiresAt", ""))
        expires_at = None
        if (
            expires_raw
            and expires_raw != "恒久"
            and "PERMANENT" not in expires_raw.upper()
        ):
            try:
                dt = datetime.strptime(expires_raw, "%Y-%m-%d")
                expires_at = dt.replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                pass

        req_id = str(req.get("requestId", str(uuid.uuid4())))
        status = "APPROVED" if is_emergency else "PENDING"

        req_type = "GRANT"
        if "変更" in raw_type or "CHANGE" in raw_type.upper():
            req_type = "CHANGE"
        elif "削除" in raw_type or "REVOKE" in raw_type.upper():
            req_type = "REVOKE"

        res_val = str(req.get("resource", "")).strip()
        if res_val and not (
            res_val.startswith("projects/")
            or res_val.startswith("folders/")
            or res_val.startswith("organizations/")
        ):
            res_val = f"projects/{res_val}"

        bq_req = {
            "request_group_id": request_group_id,
            "request_id": req_id,
            "request_type": req_type,
            "principal_email": str(req.get("principal", "")).strip(),
            "resource_name": res_val,
            "role": role,
            "reason": reason,
            "expires_at": expires_at,
            "requester_email": requester_email,
            "approver_email": str(req.get("approver", "")).strip(),
            "status": status,
            "requested_at": requested_at,
            "ticket_ref": "",
        }
        bq_requests.append(bq_req)

        history_events.append(
            {
                "history_id": str(uuid.uuid4()),
                "request_id": req_id,
                "request_group_id": request_group_id,
                "event_type": "REQUESTED",
                "old_status": "",
                "new_status": status,
                "reason_snapshot": reason,
                "request_type": req_type,
                "principal_email": bq_req["principal_email"],
                "resource_name": bq_req["resource_name"],
                "role": role,
                "requester_email": requester_email,
                "approver_email": bq_req["approver_email"],
                "acted_by": requester_email,
                "actor_source": "WEB_APP_BULK",
                "event_at": requested_at,
                "details": {
                    "source": "web_app_bulk",
                    "ai_suggestion": str(req.get("aiSuggestion", "")),
                },
            }
        )
        if is_emergency:
            emergency_ids.append(req_id)

    try:
        repo.insert_access_requests_raw_bulk(bq_requests)
        repo.insert_request_history_events_bulk(history_events)
        for eid in emergency_ids:
            _execute_request_by_id(eid)
        return jsonify(
            {
                "result": "SUCCESS",
                "inserted_count": len(bq_requests),
                "request_group_id": request_group_id,
            }
        )
    except Exception as exc:
        logging.error(f"UI Bulk Submit failed: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


def _build_collection_error_report(
    *, job_type: str, execution_id: str, exc: Exception
) -> dict[str, Any]:
    """
    データ収集ジョブの失敗時に、詳細なエラーレポートを生成します。

    Args:
        job_type (str): 失敗したジョブの種類。
        execution_id (str): 実行ID。
        exc (Exception): 発生した例外。

    Returns:
        dict[str, Any]: エラーレポートの詳細を含む辞書。
    """
    logging.error(
        f"Pipeline job {job_type} failed (Execution ID: {execution_id}): {exc}"
    )
    error_code = type(exc).__name__
    error_message = str(exc)
    hint = "Check Cloud Run logs for details."
    result = "FAILED"
    http_status = 500

    if isinstance(exc, GcpPermissionDenied):
        result = "FAILED_PERMISSION"
        http_status = 200
        hint = _permission_hint(job_type)
    elif (
        isinstance(exc, HttpError)
        and exc.resp is not None
        and int(exc.resp.status) in (401, 403)
    ):
        result = "FAILED_PERMISSION"
        http_status = 200
        hint = _permission_hint(job_type)

    return {
        "execution_id": execution_id,
        "job_type": job_type,
        "result": result,
        "error_code": error_code,
        "error_message": error_message,
        "hint": hint,
        "counts": {},
        "details": {},
        "http_status": http_status,
    }


def _permission_hint(job_type: str) -> str:
    """
    権限エラーが発生した場合の解決策に関するヒントを返します。

    Args:
        job_type (str): ジョブの種類。

    Returns:
        str: 解決策のヒント文字列。
    """
    if job_type == "RESOURCE_COLLECTION":
        return (
            "Grant roles/cloudasset.viewer to executor SA on managed scope "
            "and verify Cloud Asset API is enabled."
        )
    if job_type == "PRINCIPAL_COLLECTION":
        return (
            "Grant Cloud Identity / Admin SDK / IAM read permissions to "
            "executor SA and verify related APIs are enabled."
        )
    return "Verify IAM permissions for this collection job."


@app.post("/jobs/discover-iam-roles")
def discover_iam_roles():
    """未知のIAMロールを検知し、Geminiで日本語訳を生成してマスタに登録するジョブ。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())
    job_type = "IAM_ROLE_DISCOVERY"

    try:
        unknown_roles = repo.get_unknown_roles()
        inserted_count = 0
        if unknown_roles:
            from .role_translator import translate_roles_with_gemini

            translated_map = translate_roles_with_gemini(PROJECT_ID, unknown_roles)

            roles_to_insert = []
            for role in unknown_roles:
                ja_name = translated_map.get(role)
                roles_to_insert.append(
                    {
                        "role_id": role,
                        "role_name_ja": ja_name,
                        "is_auto_translated": True if ja_name else False,
                    }
                )
            inserted_count = repo.insert_role_master(roles_to_insert)

        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type=job_type,
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts={
                "discovered_roles": len(unknown_roles),
                "inserted_roles": inserted_count,
            },
            details={"note": "Roles auto-translated by Gemini"},
        )
        return jsonify(
            {
                "execution_id": execution_id,
                "result": "SUCCESS",
                "inserted": inserted_count,
            }
        )
    except Exception as exc:
        report = _build_collection_error_report(
            job_type=job_type, execution_id=execution_id, exc=exc
        )
        report_for_db = {k: v for k, v in report.items() if k != "http_status"}
        repo.insert_pipeline_job_report(**report_for_db)
        return (
            jsonify(
                {
                    "execution_id": execution_id,
                    "result": report["result"],
                    "error_code": report["error_code"],
                    "error_message": report["error_message"],
                    "hint": report["hint"],
                }
            ),
            report["http_status"],
        )
