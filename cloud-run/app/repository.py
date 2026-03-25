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
