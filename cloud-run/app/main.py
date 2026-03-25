from __future__ import annotations

import os
import traceback
import uuid

from flask import Flask, jsonify, request

from .iam_executor import IamExecutor
from .models import ExecutionResult
from .repository import Repository
from .scope_validator import ScopeConfig, ScopeValidator


app = Flask(__name__)

PROJECT_ID = os.environ["BQ_PROJECT_ID"]
DATASET_ID = os.environ["BQ_DATASET_ID"]
EXECUTOR_IDENTITY = os.environ.get("EXECUTOR_IDENTITY", "cloud-run")
SHARED_SECRET = os.environ.get("WEBHOOK_SHARED_SECRET", "")
TARGET_PROJECT_ID = os.environ.get("MGMT_TARGET_PROJECT_ID", "").strip()
TARGET_ORG_ID = os.environ.get("MGMT_TARGET_ORGANIZATION_ID", "").strip()

repo = Repository(project_id=PROJECT_ID, dataset_id=DATASET_ID)
iam_executor = IamExecutor()
scope_validator = ScopeValidator(
    ScopeConfig(
        target_project_id=TARGET_PROJECT_ID,
        target_org_id=TARGET_ORG_ID,
    )
)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.post("/execute")
def execute_request():
    execution_id = str(uuid.uuid4())

    if SHARED_SECRET:
        token = request.headers.get("X-Webhook-Token", "")
        if token != SHARED_SECRET:
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
        return jsonify({"execution_id": execution_id, "result": result.result, "reason": "status_not_approved"})

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
        return jsonify({"execution_id": execution_id, "result": result.result, "reason": "idempotent_skip"})

    try:
        result = iam_executor.execute(req)
    except Exception as exc:  # pragma: no cover
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
