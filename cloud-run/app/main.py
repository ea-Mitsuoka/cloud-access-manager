from __future__ import annotations

import logging
import os
import traceback
import uuid
from dataclasses import replace
from typing import Any

from flask import Flask, jsonify, request
from google.api_core.exceptions import PermissionDenied as GcpPermissionDenied
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from googleapiclient.errors import HttpError

from .iam_executor import IamExecutor
from .models import ExecutionResult
from .iam_policy_collector import IamPolicyCollector
from .google_group_collector import GoogleGroupCollector
from .resource_inventory_collector import ResourceInventoryCollector
from .repository import Repository
from .scope_validator import ScopeConfig, ScopeValidator

app = Flask(__name__)

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
group_collector = GoogleGroupCollector(
    workspace_customer_id=WORKSPACE_CUSTOMER_ID,
    source="cloudidentity",
)
iam_policy_collector = IamPolicyCollector(
    target_project_id=TARGET_PROJECT_ID,
    target_org_id=TARGET_ORG_ID,
)


@app.get("/healthz")
def healthz():
    """ヘルスチェックエンドポイント。

    Returns:
        Response: 常に {"ok": True} を含むJSONレスポンス。
    """
    return jsonify({"ok": True})


@app.post("/execute")
def execute_request():
    """
    承認済みのアクセスリクエストに基づいてIAMポリシー変更を実行します。

    Returns:
        Response: 実行結果を含むJSONレスポンス。
    """
    execution_id = str(uuid.uuid4())

    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    request_id = str(payload.get("request_id", "")).strip()
    if not request_id:
        return jsonify({"error": "request_id is required"}), 400

    req = repo.get_approved_request(request_id)
    if req is None:
        return jsonify({"error": f"request_id not found: {request_id}"}), 404

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
        return jsonify(
            {
                "execution_id": execution_id,
                "result": result.result,
                "reason": "status_not_approved",
            }
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
            jsonify(
                {
                    "execution_id": execution_id,
                    "request_id": request_id,
                    "result": result.result,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                }
            ),
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
        return jsonify(
            {
                "execution_id": execution_id,
                "result": result.result,
                "reason": "idempotent_skip",
            }
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
        jsonify(
            {
                "execution_id": execution_id,
                "request_id": request_id,
                "result": result.result,
                "error_code": result.error_code,
                "error_message": result.error_message,
            }
        ),
        http_status,
    )


@app.post("/collect/resources")
def collect_resources():
    """
    管理対象スコープ内のGCPリソースを収集し、棚卸しデータをDBに保存します。

    Returns:
        Response: 収集結果を含むJSONレスポンス。
    """
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

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


@app.post("/collect/groups")
def collect_groups():
    """
    Google Workspace (Cloud Identity) からグループとメンバーシップ情報を収集し、DBを更新します。

    Returns:
        Response: 収集結果を含むJSONレスポンス。
    """
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())

    try:
        group_rows, membership_rows, counts = group_collector.collect(
            execution_id=execution_id
        )
        replaced_groups = repo.replace_groups(group_rows, source=group_collector.source)
        inserted_memberships = repo.insert_group_membership_rows(membership_rows)
        counts_for_report = {
            "groups_replaced": replaced_groups,
            "memberships_inserted": (inserted_memberships),
            **counts,
        }
        repo.insert_pipeline_job_report(
            execution_id=execution_id,
            job_type="GROUP_COLLECTION",
            result="SUCCESS",
            error_code=None,
            error_message=None,
            hint=None,
            counts=counts_for_report,
            details={"source": group_collector.source},
        )
    except Exception as exc:  # pragma: no cover
        report = _build_collection_error_report(
            job_type="GROUP_COLLECTION",
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
            "groups_replaced": replaced_groups,
            "memberships_inserted": inserted_memberships,
            "counts": counts,
        }
    )


@app.post("/collect/iam-policies")
def collect_iam_policies():
    """管理対象スコープ内のIAMポリシーを収集し、DBを洗い替えます。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

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
def reconcile_iam_issues():
    """
    IAMの矛盾を検出し、issuesテーブルに記録するリコンシリエーションジョブを実行します。

    Returns:
        Response: 実行結果を含むJSONレスポンス。
    """
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

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
def revoke_expired_permissions():
    """
    期限切れの承認済みアクセス権限を自動的に取り消します。

    Returns:
        Response: 実行結果（取り消し、スキップ、失敗の件数）を含むJSONレスポンス。
    """
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

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
def update_iam_bindings_history():
    """
    現在のIAMバインディングのスナップショットを履歴テーブルに保存するジョブを実行します。

    Returns:
        Response: 実行結果（挿入された行数）を含むJSONレスポンス。
    """
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    execution_id = str(payload.get("execution_id", "")).strip() or str(uuid.uuid4())
    job_type = "IAM_BINDINGS_HISTORY_UPDATE"

    try:
        # 1. プリンシパルマスタの同期
        repo.sync_principal_catalog()

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
def api_get_statuses():
    """GAS等のクライアント向けにステータスマスタの対応表を提供します。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401
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
def api_create_request():
    """新規アクセスリクエストを登録します。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    try:
        repo.insert_access_request_raw(payload)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to create request: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/requests/bulk-status")
def api_bulk_update_request_status():
    """複数のアクセスリクエストのステータスを一括更新し、履歴を記録します。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    updates = payload.get("updates", [])
    actor_email = payload.get("actor_email", "system")

    if not updates:
        return jsonify({"result": "SUCCESS", "updated_count": 0})

    try:
        # バックエンド主導のセキュアな更新メソッドを呼び出す
        processed_ids = repo.bulk_update_request_status_and_history_secure(
            updates=updates, actor_email=actor_email, actor_source="SHEET_EDIT_BULK"
        )
        return jsonify({"result": "SUCCESS", "updated_count": len(processed_ids)})
    except Exception as exc:
        logging.error(f"Failed to bulk update status: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.put("/api/requests/<request_id>/status")
def api_update_request_status(request_id):
    """アクセスリクエストのステータスを更新します。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not status:
        return jsonify({"error": "status is required"}), 400
    try:
        repo.update_request_status(request_id, status)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to update request status: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/history")
def api_create_history():
    """リクエスト履歴イベントを登録します。"""
    if not _authorize():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    try:
        repo.insert_request_history_event(payload)
        return jsonify({"result": "SUCCESS"})
    except Exception as exc:
        logging.error(f"Failed to create history: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


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

    # Cloud Runコンテナ内部ではhttpとして扱われるため、Audience検証用にhttpsへ強制する
    expected_audience = request.url_root.rstrip("/").replace("http://", "https://")
    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_auth_requests.Request(), expected_audience
        )
    except Exception as e:
        logging.warning(f"OIDC verification failed: {e}")
        return False

    email = str(claims.get("email", "")).strip().lower()
    allowed_emails = [
        e.lower() for e in (SCHEDULER_INVOKER_EMAIL, GAS_INVOKER_EMAIL) if e
    ]
    return email in allowed_emails


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
    if job_type == "GROUP_COLLECTION":
        return (
            "Grant Cloud Identity/Workspace group read permissions to "
            "executor SA and verify cloudidentity.googleapis.com is enabled."
        )
    return "Verify IAM permissions for this collection job."
