from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from .models import AccessRequest, ExecutionResult


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
        return f"{self._project_id}.{self._dataset_id}.gcp_resource_inventory_history"

    @property
    def groups_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.google_groups"

    @property
    def group_membership_history_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.google_group_membership_history"

    @property
    def pipeline_job_reports_table(self) -> str:
        return f"{self._project_id}.{self._dataset_id}.pipeline_job_reports"

    def get_approved_request(self, request_id: str) -> AccessRequest | None:
        sql = f"""
        SELECT
          request_id,
          request_type,
          principal_email,
          resource_name,
          role,
          status,
          approved_at
        FROM `{self.requests_table}`
        WHERE request_id = @request_id
        LIMIT 1
        """
        params = [bigquery.ScalarQueryParameter("request_id", "STRING", request_id)]
        rows = list(self._client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
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
        )

    def has_success_execution(self, request_id: str) -> bool:
        sql = f"""
        SELECT COUNT(1) AS cnt
        FROM `{self.change_log_table}`
        WHERE request_id = @request_id
          AND result = 'SUCCESS'
        """
        params = [bigquery.ScalarQueryParameter("request_id", "STRING", request_id)]
        row = next(self._client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
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

    def insert_resource_inventory_rows(self, rows: list[dict[str, Any]], chunk_size: int = 500) -> int:
        if not rows:
            return 0

        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            errors = self._client.insert_rows_json(self.resource_inventory_history_table, chunk)
            if errors:
                raise RuntimeError(f"failed to insert resource inventory rows: {errors}")
            inserted += len(chunk)
        return inserted

    def replace_groups(self, rows: list[dict[str, Any]], source: str) -> int:
        delete_sql = f"DELETE FROM `{self.groups_table}` WHERE source = @source"
        params = [bigquery.ScalarQueryParameter("source", "STRING", source)]
        self._client.query(delete_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

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

    def insert_group_membership_rows(self, rows: list[dict[str, Any]], chunk_size: int = 500) -> int:
        if not rows:
            return 0
        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            errors = self._client.insert_rows_json(self.group_membership_history_table, chunk)
            if errors:
                raise RuntimeError(f"failed to insert group membership rows: {errors}")
            inserted += len(chunk)
        return inserted

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
