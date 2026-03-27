from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from .models import AccessRequest, ExpiredAccessRequest, ExecutionResult


class Repository:
    def __init__(self, project_id: str, dataset_id: str) -> None:
        self._client = bigquery.Client(project=project_id)
        self._project_id = project_id
        self._dataset_id = dataset_id

    @property
    def requests_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.iam_access_requests"

    @property
    def change_log_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.iam_access_change_log"

    @property
    def resource_inventory_history_table(self) -> str:
        return (
            f"{self._project_id}.{self._dataset_id}" ".gcp_resource_inventory_history"
        )

    @property
    def groups_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.google_groups"

    @property
    def group_membership_history_table(self) -> str:
        return (
            f"{self._project_id}.{self._dataset_id}" ".google_group_membership_history"
        )

    @property
    def pipeline_job_reports_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.iam_pipeline_job_reports"

    def get_approved_request(self, request_id: str) -> AccessRequest | None:
        sql = f"""
        SELECT
          request_id,
          request_type,
          principal_email,
          resource_name,
          role,
          status,
          approved_at,
          reason
        FROM `{self.requests_table}`
        WHERE request_id = @request_id
        LIMIT 1
        """
        params = [bigquery.ScalarQueryParameter("request_id", "STRING", request_id)]
        rows = list(
            self._client.query(
                sql,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result()
        )
        if not rows:
            return None

        row = rows[0]
        return AccessRequest(
            request_id=row["request_id"],
            request_type=row["request_type"],
            principal_email=row["principal_email"],
            resource_name=row["resource_name"],
            role=row["role"],
            status=row["status"],
            approved_at=row["approved_at"],
            reason=row["reason"],
        )

    def has_success_execution(self, request_id: str) -> bool:
        sql = f"""
        SELECT COUNT(1) AS cnt
        FROM `{self.change_log_table}`
        WHERE request_id = @request_id
          AND result = 'SUCCESS'
        """
        params = [bigquery.ScalarQueryParameter("request_id", "STRING", request_id)]
        row = next(
            self._client.query(
                sql,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result()
        )
        return int(row["cnt"]) > 0

    def insert_change_log(
        self,
        execution_id: str,
        request_id: str,
        executed_by: str,
        result: ExecutionResult,
    ) -> None:
        rows: list[dict[str, Any]] = [
            {
                "execution_id": execution_id,
                "request_id": request_id,
                "action": result.action,
                "target": result.target,
                "before_hash": result.before_hash,
                "after_hash": result.after_hash,
                "result": result.result,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "executed_by": executed_by,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "details": result.details or {},
            }
        ]
        errors = self._client.insert_rows_json(self.change_log_table, rows)
        if errors:
            raise RuntimeError(f"failed to insert change log: {errors}")

    def insert_resource_inventory_rows(
        self, rows: list[dict[str, Any]], chunk_size: int = 500
    ) -> int:
        if not rows:
            return 0

        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            errors = self._client.insert_rows_json(
                self.resource_inventory_history_table, chunk
            )
            if errors:
                raise RuntimeError(
                    "failed to insert resource inventory rows: {}".format(errors)
                )
            inserted += len(chunk)
        return inserted

    def replace_groups(self, rows: list[dict[str, Any]], source: str) -> int:
        delete_sql = f"DELETE FROM `{self.groups_table}` WHERE source = @source"
        params = [bigquery.ScalarQueryParameter("source", "STRING", source)]
        self._client.query(
            delete_sql,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result()

        if not rows:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        payload = []
        for row in rows:
            payload.append(
                {
                    "group_email": row["group_email"],
                    "group_name": row.get("group_name"),
                    "description": row.get("description"),
                    "source": source,
                    "updated_at": now,
                }
            )

        errors = self._client.insert_rows_json(self.groups_table, payload)
        if errors:
            raise RuntimeError(f"failed to replace groups: {errors}")
        return len(payload)

    def insert_group_membership_rows(
        self, rows: list[dict[str, Any]], chunk_size: int = 500
    ) -> int:
        if not rows:
            return 0
        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            errors = self._client.insert_rows_json(
                self.group_membership_history_table, chunk
            )
            if errors:
                raise RuntimeError(f"failed to insert group membership rows: {errors}")
            inserted += len(chunk)
        return inserted

    @property
    def iam_policy_permissions_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.iam_policy_permissions"

    def get_iam_policy_permission(
        self, principal_email: str, role: str, resource_name: str
    ) -> dict[str, Any] | None:
        sql = f"""
        SELECT 1
        FROM `{self.iam_policy_permissions_table}`
        WHERE principal_email = @principal_email
          AND role = @role
          AND resource_name = @resource_name
        LIMIT 1
        """
        params = [
            bigquery.ScalarQueryParameter("principal_email", "STRING", principal_email),
            bigquery.ScalarQueryParameter("role", "STRING", role),
            bigquery.ScalarQueryParameter("resource_name", "STRING", resource_name),
        ]
        rows = list(
            self._client.query(
                sql,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result()
        )
        if not rows:
            return None
        return rows[0]

    def update_request_status(self, request_id: str, status: str) -> None:
        sql = f"""
        UPDATE `{self.requests_table}`
        SET status = @status
        WHERE request_id = @request_id
        """
        params = [
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("request_id", "STRING", request_id),
        ]
        self._client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result()

    def search_expired_approved_access_requests(
        self,
    ) -> list[ExpiredAccessRequest]:
        sql = f"""
        SELECT
          req.request_id,
          req.request_type,
          req.principal_email,
          req.resource_name,
          req.role,
          req.status,
          req.approved_at,
          req.expires_at,
          (perm.principal_email IS NOT NULL) AS is_permission_active
        FROM `{self.requests_table}` AS req
        LEFT JOIN `{self.iam_policy_permissions_table}` AS perm
          ON req.principal_email = perm.principal_email
          AND req.role = perm.role
          AND req.resource_name = perm.resource_name
        WHERE req.status = 'APPROVED'
          AND req.expires_at IS NOT NULL
          AND req.expires_at < CURRENT_TIMESTAMP()
        """
        rows = self._client.query(sql).result()
        requests = []
        for row in rows:
            requests.append(
                ExpiredAccessRequest(
                    request_id=row["request_id"],
                    request_type=row["request_type"],
                    principal_email=row["principal_email"],
                    resource_name=row["resource_name"],
                    role=row["role"],
                    status=row["status"],
                    approved_at=row["approved_at"],
                    expires_at=row["expires_at"],
                    is_permission_active=row["is_permission_active"],
                )
            )
        return requests

    def insert_pipeline_job_report(
        self,
        *,
        execution_id: str,
        job_type: str,
        result: str,
        error_code: str | None,
        error_message: str | None,
        hint: str | None,
        counts: dict[str, Any] | None,
        details: dict[str, Any] | None,
    ) -> None:
        rows: list[dict[str, Any]] = [
            {
                "execution_id": execution_id,
                "job_type": job_type,
                "result": result,
                "error_code": error_code,
                "error_message": error_message,
                "hint": hint,
                "counts": counts or {},
                "details": details or {},
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        errors = self._client.insert_rows_json(self.pipeline_job_reports_table, rows)
        if errors:
            raise RuntimeError(f"failed to insert pipeline job report: {errors}")

    def run_reconciliation_job(self) -> int:
        sql = f"""
        INSERT INTO
          `{self._project_id}.{self._dataset_id}.iam_reconciliation_issues` (
          issue_id,
          issue_type,
          request_id,
          principal_email,
          resource_name,
          role,
          detected_at,
          severity,
          status,
          details
        )
        WITH requests AS (
          SELECT
            request_id,
            request_type,
            principal_email,
            resource_name,
            role,
            status,
            expires_at
          FROM `{self.requests_table}`
        ),
        actual AS (
          SELECT
            principal_email,
            resource_name,
            role,
            TRUE AS exists_now
          FROM `{self.iam_policy_permissions_table}`
        ),
        joined AS (
          SELECT
            r.*,
            IFNULL(a.exists_now, FALSE) AS exists_now
          FROM requests r
          LEFT JOIN actual a USING (principal_email, resource_name, role)
        )
        SELECT
          FORMAT(
            '%s-%s-%s', request_id, issue_type, FORMAT_TIMESTAMP(
                '%Y%m%d%H%M%S', CURRENT_TIMESTAMP())
                ) AS issue_id,
          issue_type,
          request_id,
          principal_email,
          resource_name,
          role,
          CURRENT_TIMESTAMP() AS detected_at,
          severity,
          'OPEN' AS status,
          TO_JSON(STRUCT(status AS request_status, exists_now, expires_at)) AS details
        FROM (
          SELECT
            request_id,
            principal_email,
            resource_name,
            role,
            CASE
              WHEN status = 'APPROVED'
                AND exists_now = FALSE
                THEN 'APPROVED_NOT_APPLIED'
              WHEN status IN ('REJECTED', 'CANCELLED')
                AND exists_now = TRUE
                THEN 'REJECTED_BUT_EXISTS'
              WHEN status = 'APPROVED'
                AND expires_at IS NOT NULL
                AND expires_at < CURRENT_TIMESTAMP()
                AND exists_now = TRUE
                THEN 'EXPIRED_BUT_EXISTS'
              ELSE NULL
            END AS issue_type,
            CASE
              WHEN status = 'APPROVED'
                AND exists_now = FALSE
                THEN 'HIGH'
              WHEN status IN ('REJECTED', 'CANCELLED')
                AND exists_now = TRUE
                THEN 'MEDIUM'
              WHEN status = 'APPROVED'
                AND expires_at IS NOT NULL
                AND expires_at < CURRENT_TIMESTAMP()
                AND exists_now = TRUE THEN 'HIGH'
              ELSE NULL
            END AS severity,
            status,
            exists_now,
            expires_at
          FROM joined
        )
        WHERE issue_type IS NOT NULL
        """
        job = self._client.query(sql)
        job.result()
        return job.num_dml_affected_rows or 0

    def run_update_bindings_history_job(self, execution_id: str) -> int:
        sql = f"""
        INSERT INTO
        `{self._project_id}.{self._dataset_id}.iam_permission_bindings_history` (
          execution_id,
          recorded_at,
          resource_name,
          resource_id,
          resource_full_path,
          principal_email,
          principal_type,
          iam_role,
          iam_condition,
          ticket_ref,
          request_reason,
          status_ja,
          approved_at,
          next_review_at,
          approver,
          request_id,
          note
        )
        SELECT
          @execution_id AS execution_id,
          CURRENT_TIMESTAMP() AS recorded_at,
          p.resource_name,
          p.resource_id,
          p.full_resource_path,
          p.principal_email,
          p.principal_type,
          p.role AS iam_role,
          p.iam_condition,
          req.ticket_ref,
          req.reason AS request_reason,
          status_map.status_ja,
          req.approved_at,
          req.expires_at AS next_review_at,
          req.approver_email AS approver,
          req.request_id,
          'Snapshot from iam_policy_permissions' AS note
        FROM `{self.iam_policy_permissions_table}` AS p
        LEFT JOIN
          `{self._project_id}.{self._dataset_id}.v_iam_request_execution_latest` AS req
          ON p.principal_email = req.principal_email
          AND p.role = req.role
          AND p.resource_name = req.resource_name
        LEFT JOIN
          `{self._project_id}.{self._dataset_id}.iam_status_master` AS status_map
          ON req.status = status_map.status_code
        """
        params = [bigquery.ScalarQueryParameter("execution_id", "STRING", execution_id)]
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        job = self._client.query(sql, job_config=job_config)
        job.result()
        return job.num_dml_affected_rows or 0
