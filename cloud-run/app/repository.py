from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from .models import AccessRequest, ExpiredAccessRequest, ExecutionResult


class Repository:
    """BigQueryをデータストアとして利用するためのリポジトリクラス。"""

    def __init__(self, project_id: str, dataset_id: str) -> None:
        """
        リポジトリを初期化します。

        Args:
            project_id (str): BigQueryのプロジェクトID。
            dataset_id (str): BigQueryのデータセットID。
        """
        self._client = bigquery.Client(project=project_id)
        self._project_id = project_id
        self._dataset_id = dataset_id

    @property
    def requests_table(self) -> str:
        """アクセスリクエストテーブルの完全なテーブルID。"""
        return f"{self._project_id}.{self._dataset_id}.iam_access_requests"

    @property
    def change_log_table(self) -> str:
        """変更履歴テーブルの完全なテーブルID。"""
        return f"{self._project_id}.{self._dataset_id}.iam_access_change_log"

    @property
    def resource_inventory_history_table(self) -> str:
        """リソース棚卸し履歴テーブルの完全なテーブルID。"""
        return (
            f"{self._project_id}.{self._dataset_id}" ".gcp_resource_inventory_history"
        )

    @property
    def groups_table(self) -> str:
        """Googleグループテーブルの完全なテーブルID。"""
        return f"{self._project_id}.{self._dataset_id}.google_groups"

    @property
    def group_membership_history_table(self) -> str:
        """Googleグループメンバーシップ履歴テーブルの完全なテーブルID。"""
        return (
            f"{self._project_id}.{self._dataset_id}" ".google_group_membership_history"
        )

    @property
    def pipeline_job_reports_table(self) -> str:
        """パイプラインジョブレポートテーブルの完全なテーブルID。"""
        return f"{self._project_id}.{self._dataset_id}.iam_pipeline_job_reports"

    def get_approved_request(self, request_id: str) -> AccessRequest | None:
        """
        承認済みのアクセスリクエストを取得します。

        Args:
            request_id (str): 取得するリクエストのID。

        Returns:
            AccessRequest | None: アクセスリクエストオブジェクト。見つからない場合はNone。
        """
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
        """
        指定されたリクエストIDに対して成功した実行ログが存在するかどうかを確認します。

        Args:
            request_id (str): 確認するリクエストのID。

        Returns:
            bool: 成功した実行ログが存在する場合はTrue、そうでない場合はFalse。
        """
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
        """
        変更履歴を記録します。

        Args:
            execution_id (str): 実行ID。
            request_id (str): リクエストID。
            executed_by (str): 実行者。
            result (ExecutionResult): 実行結果。

        Raises:
            RuntimeError: ログの挿入に失敗した場合。
        """
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
        """
        リソース棚卸しデータを挿入します。

        Args:
            rows (list[dict[str, Any]]): 挿入するデータのリスト。
            chunk_size (int, optional): 一度に挿入する行数。デフォルトは500。

        Returns:
            int: 挿入された行数。

        Raises:
            RuntimeError: 挿入に失敗した場合。
        """
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
        """
        指定されたソースのGoogleグループを洗い替えます。

        Args:
            rows (list[dict[str, Any]]): 新しいグループデータのリスト。
            source (str): データのソース（例: "cloudidentity"）。

        Returns:
            int: 挿入された行数。

        Raises:
            RuntimeError: 挿入に失敗した場合。
        """
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

        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        job = self._client.load_table_from_json(
            payload, self.groups_table, job_config=job_config
        )
        job.result()
        return job.output_rows

    def insert_group_membership_rows(
        self, rows: list[dict[str, Any]], chunk_size: int = 500
    ) -> int:
        """
        Googleグループのメンバーシップデータを挿入します。

        Args:
            rows (list[dict[str, Any]]): 挿入するデータのリスト。
            chunk_size (int, optional): 一度に挿入する行数。デフォルトは500。

        Returns:
            int: 挿入された行数。

        Raises:
            RuntimeError: 挿入に失敗した場合。
        """
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
        """IAMポリシー権限テーブルの完全なテーブルID。"""
        return f"{self._project_id}.{self._dataset_id}.iam_policy_permissions"

    def replace_iam_policy_permissions(self, rows: list[dict[str, Any]]) -> int:
        """IAMポリシーテーブルを洗い替えます (WRITE_TRUNCATE)。"""
        if not rows:
            query = f"TRUNCATE TABLE `{self.iam_policy_permissions_table}`"
            self._client.query(query).result()
            return 0

        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        job = self._client.load_table_from_json(
            rows, self.iam_policy_permissions_table, job_config=job_config
        )
        job.result()
        return job.output_rows

    def get_iam_policy_permission(
        self, principal_email: str, role: str, resource_name: str
    ) -> dict[str, Any] | None:
        """
        指定された条件でIAMポリシー権限が存在するかどうかを確認します。

        Args:
            principal_email (str): プリンシパルのメールアドレス。
            role (str): IAMロール。
            resource_name (str): リソース名。

        Returns:
            dict[str, Any] | None: 権限が存在する場合は行データ、そうでない場合はNone。
        """
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

    def get_status_master(self) -> dict[str, str]:
        """DBからステータスマスタを取得し、日本語名とコードの対応辞書を返します。"""
        sql = f"SELECT status_ja, status_code FROM `{self._project_id}.{self._dataset_id}.iam_status_master` WHERE is_active"
        rows = self._client.query(sql).result()
        return {
            row["status_ja"]: row["status_code"] for row in rows if row["status_code"]
        }

    def insert_access_request_raw(self, row: dict[str, Any]) -> None:
        """
        新規アクセスリクエストをDML(INSERT INTO)で記録します。
        ※直後のステータスUPDATE（緊急承認フロー等）を確実に成功させるため、
        BigQueryのストリーミングバッファ制限を回避します。
        """
        sql = f"""
        INSERT INTO `{self.requests_table}` (
            request_id, request_type, principal_email, resource_name, role,
            reason, expires_at, requester_email, approver_email, status,
            requested_at, ticket_ref, created_at, updated_at
        ) VALUES (
            @request_id, @request_type, @principal_email, @resource_name, @role,
            @reason, @expires_at, @requester_email, @approver_email, @status,
            @requested_at, @ticket_ref, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
        )
        """
        params = [
            bigquery.ScalarQueryParameter(
                "request_id", "STRING", row.get("request_id")
            ),
            bigquery.ScalarQueryParameter(
                "request_type", "STRING", row.get("request_type")
            ),
            bigquery.ScalarQueryParameter(
                "principal_email", "STRING", row.get("principal_email")
            ),
            bigquery.ScalarQueryParameter(
                "resource_name", "STRING", row.get("resource_name")
            ),
            bigquery.ScalarQueryParameter("role", "STRING", row.get("role")),
            bigquery.ScalarQueryParameter("reason", "STRING", row.get("reason")),
            bigquery.ScalarQueryParameter(
                "expires_at", "TIMESTAMP", row.get("expires_at")
            ),
            bigquery.ScalarQueryParameter(
                "requester_email", "STRING", row.get("requester_email")
            ),
            bigquery.ScalarQueryParameter(
                "approver_email", "STRING", row.get("approver_email")
            ),
            bigquery.ScalarQueryParameter("status", "STRING", row.get("status")),
            bigquery.ScalarQueryParameter(
                "requested_at", "TIMESTAMP", row.get("requested_at")
            ),
            bigquery.ScalarQueryParameter(
                "ticket_ref", "STRING", row.get("ticket_ref")
            ),
        ]
        self._client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result()

    def insert_request_history_event(self, row: dict[str, Any]) -> None:
        """アクセスリクエストの履歴イベントをStreaming Insertで記録します。"""
        table = f"{self._project_id}.{self._dataset_id}.iam_access_request_history"
        errors = self._client.insert_rows_json(table, [row])
        if errors:
            raise RuntimeError(f"failed to insert request history: {errors}")

    def update_request_status(self, request_id: str, status: str) -> None:
        """
        アクセスリクエストのステータスを更新します。
        """
        set_clause = "status = @status, updated_at = CURRENT_TIMESTAMP()"
        if status == "APPROVED":
            set_clause += ", approved_at = CURRENT_TIMESTAMP()"

        sql = f"""
        UPDATE `{self.requests_table}`
        SET {set_clause}
        WHERE request_id = @request_id
        """

        params = [
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("request_id", "STRING", request_id),
        ]
        self._client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result()


    def bulk_update_request_status_and_history_secure(
        self,
        updates: list[dict],
        actor_email: str = "SYSTEM",
        actor_source: str = "SYSTEM_BATCH"
    ) -> list[str]:
        if not updates:
            return []

        import uuid
        from datetime import datetime, timezone
        from google.cloud import bigquery
        
        req_ids = [u.get("request_id") for u in updates if u.get("request_id")]
        if not req_ids:
            return []
        
        # 1. バックエンド側で安全に現在のスナップショットを取得する（SQLインジェクション防止）
        query = f"SELECT * FROM `{self.requests_table}` WHERE request_id IN UNNEST(@req_ids)"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("req_ids", "STRING", req_ids)]
        )
        rows = self._client.query(query, job_config=job_config).result()
        snapshots = {row["request_id"]: dict(row) for row in rows}
        
        history_rows = []
        now_str = datetime.now(timezone.utc).isoformat()
        processed_ids = []
        
        # 2. 履歴データの構築と更新クエリの実行
        for u in updates:
            req_id = u.get("request_id")
            new_status = u.get("status")
            snap = snapshots.get(req_id)
            
            if not snap or snap.get("status") == new_status:
                continue
                
            history_id = str(uuid.uuid4())
            history_rows.append({
                "history_id": history_id,
                "request_id": req_id,
                "event_type": "STATUS_CHANGED",
                "old_status": snap.get("status", ""),
                "new_status": new_status,
                "reason_snapshot": snap.get("reason", ""),
                "request_type": snap.get("request_type", ""),
                "principal_email": snap.get("principal_email", ""),
                "resource_name": snap.get("resource_name", ""),
                "role": snap.get("role", ""),
                "requester_email": snap.get("requester_email", ""),
                "approver_email": snap.get("approver_email", ""),
                "acted_by": actor_email,
                "actor_source": actor_source,
                "event_at": now_str,
                "details": {"note": "Bulk status update"}
            })
            
            # 安全なパラメータ化クエリによる単一更新
            update_query = f"""
                UPDATE `{self.requests_table}`
                SET status = @new_status, updated_at = CURRENT_TIMESTAMP(),
                    approved_at = CASE WHEN @new_status = 'APPROVED' THEN CURRENT_TIMESTAMP() ELSE approved_at END
                WHERE request_id = @req_id
            """
            u_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("new_status", "STRING", new_status),
                    bigquery.ScalarQueryParameter("req_id", "STRING", req_id)
                ]
            )
            self._client.query(update_query, job_config=u_config).result()
            processed_ids.append(history_id)

        # 3. 履歴の書き込み
        if history_rows:
            errors = self._client.insert_rows_json(
                f"{self._project_id}.{self._dataset_id}.iam_access_request_history",
                history_rows,
            )
            if errors:
                raise RuntimeError(f"failed to insert bulk history: {errors}")
                
        return processed_ids

    def bulk_update_request_status_and_history(
        self,
        updates: list[tuple[ExpiredAccessRequest, str]],
        actor: str = "SYSTEM_AUTO_REVOKE",
    ) -> None:
        """
        複数のリクエストのステータスを一括で更新し、同時に履歴イベントも記録します。
        BigQueryのDML競合エラーとN+1パフォーマンス問題を完全に回避します。
        """
        if not updates:
            return

        # 1. 履歴テーブルへのバルクINSERT (Streaming Insert)
        import uuid

        history_rows = []
        now_str = datetime.now(timezone.utc).isoformat()
        for req, new_status in updates:
            history_rows.append(
                {
                    "history_id": str(uuid.uuid4()),
                    "request_id": req.request_id,
                    "event_type": "STATUS_CHANGED",
                    "old_status": req.status,
                    "new_status": new_status,
                    "reason_snapshot": req.reason or "",
                    "request_type": req.request_type,
                    "principal_email": req.principal_email,
                    "resource_name": req.resource_name,
                    "role": req.role,
                    "requester_email": "system",
                    "approver_email": "system",
                    "acted_by": actor,
                    "actor_source": "SYSTEM_BATCH",
                    "event_at": now_str,
                    "details": {"note": "Expired permission automatically revoked"},
                }
            )
        if history_rows:
            errors = self._client.insert_rows_json(
                f"{self._project_id}.{self._dataset_id}.iam_access_request_history",
                history_rows,
            )
            if errors:
                raise RuntimeError(f"failed to insert bulk history: {errors}")

        # 2. メインテーブルのバルクUPDATE (DML 1回)
        cases = []
        request_ids = []
        for req, new_status in updates:
            cases.append(f"WHEN request_id = '{req.request_id}' THEN '{new_status}'")
            request_ids.append(f"'{req.request_id}'")

        case_statement = " ".join(cases)
        id_list = ", ".join(request_ids)

        sql = f"""
        UPDATE `{self.requests_table}`
        SET
            status = CASE {case_statement} ELSE status END,
            updated_at = CURRENT_TIMESTAMP()
        WHERE request_id IN ({id_list})
        """
        self._client.query(sql).result()

    def search_expired_approved_access_requests(
        self,
    ) -> list[ExpiredAccessRequest]:
        """
        期限切れの承認済みアクセスリクエストを検索します。

        Returns:
            list[ExpiredAccessRequest]: 期限切れのアクセスリクエストのリスト。
        """
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
          AND req.request_type != 'REVOKE'
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
        """
        パイプラインのジョブレポートを挿入します。

        Args:
            execution_id (str): 実行ID。
            job_type (str): ジョブの種類。
            result (str): 結果 (SUCCESS, FAILEDなど)。
            error_code (str | None): エラーコード。
            error_message (str | None): エラーメッセージ。
            hint (str | None): ヒント。
            counts (dict[str, Any] | None): カウント情報。
            details (dict[str, Any] | None): 詳細情報。

        Raises:
            RuntimeError: 挿入に失敗した場合。
        """
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
        """
        リコンシリエーションジョブを実行し、矛盾を検出して記録します。
        """
        sql = f"""
        INSERT INTO
          `{self._project_id}.{self._dataset_id}.iam_reconciliation_issues` (
          issue_id, issue_type, request_id, principal_email, resource_name, role, detected_at, severity, status, details
        )
        WITH requests AS (
          SELECT request_id, request_type, principal_email, resource_name, role, status, expires_at
          FROM (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY principal_email, resource_name, role ORDER BY requested_at DESC) AS rn
            FROM `{self.requests_table}`
          )
          WHERE rn = 1
        ),
        actual AS (
          SELECT DISTINCT principal_email, resource_name, role, TRUE AS exists_now
          FROM `{self.iam_policy_permissions_table}`
        ),
        joined AS (
          SELECT
            r.request_id,
            COALESCE(r.principal_email, a.principal_email) AS principal_email,
            COALESCE(r.resource_name, a.resource_name) AS resource_name,
            COALESCE(r.role, a.role) AS role,
            r.request_type,
            r.status,
            r.expires_at,
            IFNULL(a.exists_now, FALSE) AS exists_now
          FROM requests r
          FULL OUTER JOIN actual a USING (principal_email, resource_name, role)
        )
        new_issues AS (
          SELECT
          FORMAT('%s-%s-%s', COALESCE(request_id, 'UNMANAGED'), issue_type, FORMAT_TIMESTAMP('%Y%m%d%H%M%S', CURRENT_TIMESTAMP())) AS issue_id,
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
            request_id, request_type, principal_email, resource_name, role,
            CASE
              WHEN COALESCE(request_type, 'GRANT') != 'REVOKE' THEN
                CASE
                  WHEN status = 'APPROVED' AND exists_now = FALSE THEN 'APPROVED_NOT_APPLIED'
                  WHEN status IN ('REJECTED', 'CANCELLED', 'REVOKED', 'REVOKED_ALREADY_GONE', 'EXPIRED') AND exists_now = TRUE THEN 'REJECTED_BUT_EXISTS'
                  WHEN status = 'APPROVED' AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP() AND exists_now = TRUE THEN 'EXPIRED_BUT_EXISTS'
                  WHEN (status IS NULL OR status = 'PENDING') AND exists_now = TRUE THEN 'UNMANAGED_BINDING'
                  ELSE NULL
                END
              WHEN request_type = 'REVOKE' THEN
                CASE
                  WHEN status = 'APPROVED' AND exists_now = TRUE THEN 'REVOKE_NOT_APPLIED'
                  ELSE NULL
                END
              ELSE NULL
            END AS issue_type,
            CASE
              WHEN COALESCE(request_type, 'GRANT') != 'REVOKE' THEN
                CASE
                  WHEN status = 'APPROVED' AND exists_now = FALSE THEN 'HIGH'
                  WHEN status IN ('REJECTED', 'CANCELLED') AND exists_now = TRUE THEN 'MEDIUM'
                  WHEN status = 'APPROVED' AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP() AND exists_now = TRUE THEN 'HIGH'
                  WHEN (status IS NULL OR status = 'PENDING') AND exists_now = TRUE THEN 'HIGH'
                  ELSE NULL
                END
              WHEN request_type = 'REVOKE' THEN
                CASE
                  WHEN status = 'APPROVED' AND exists_now = TRUE THEN 'HIGH'
                  ELSE NULL
                END
              ELSE NULL
            END AS severity,
            status, exists_now, expires_at
          FROM joined
        )
        WHERE issue_type IS NOT NULL
        )
        SELECT n.*
        FROM new_issues n
        WHERE n.issue_type IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM `{self._project_id}.{self._dataset_id}.iam_reconciliation_issues` e
            WHERE e.status = 'OPEN'
              AND e.issue_type = n.issue_type
              AND COALESCE(e.principal_email, '') = COALESCE(n.principal_email, '')
              AND COALESCE(e.resource_name, '') = COALESCE(n.resource_name, '')
              AND COALESCE(e.role, '') = COALESCE(n.role, '')
          )
        """
        job = self._client.query(sql)
        job.result()
        return job.num_dml_affected_rows or 0

    def run_update_bindings_history_job(self, execution_id: str) -> int:
        """
        現在のIAMポリシーバインディングのスナップショットを履歴テーブルに保存します。

        Args:
            execution_id (str): このジョブ実行のユニークID。

        Returns:
            int: 挿入された行数。
        """
        sql = f"""
        INSERT INTO
        `{self._project_id}.{self._dataset_id}.iam_permission_bindings_history` (
          execution_id,
          recorded_at,
          resource_name,
          resource_id,
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
          REGEXP_EXTRACT(p.resource_name, r'^projects/([^/]+)') AS resource_id,
          p.principal_email,
          p.principal_type,
          p.role AS iam_role,
          CAST(NULL AS STRING) AS iam_condition,
          req.ticket_ref,
          req.reason AS request_reason,
          status_map.status_ja,
          req.approved_at,
          CAST(req.expires_at AS DATE) AS next_review_at,
          req.approver_email AS approver,
          req.request_id,
          'Snapshot from iam_policy_permissions' AS note
        FROM `{self.iam_policy_permissions_table}` AS p
        LEFT JOIN (
          SELECT * FROM `{self._project_id}.{self._dataset_id}.v_iam_request_execution_latest`
          QUALIFY ROW_NUMBER() OVER(PARTITION BY principal_email, role, resource_name ORDER BY requested_at DESC) = 1
        ) AS req
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

    def sync_principal_catalog(self) -> int:
        """
        現在のIAM権限状態からプリンシパルマスタを同期（MERGE）します。

        Returns:
            int: 挿入または更新された行数。
        """
        sql = f"""
        MERGE `{self._project_id}.{self._dataset_id}.principal_catalog` T
        USING (
          SELECT
            principal_email,
            ANY_VALUE(principal_type) AS principal_type
          FROM `{self.iam_policy_permissions_table}`
          WHERE principal_email IS NOT NULL AND principal_email != ''
          GROUP BY principal_email
        ) S
        ON T.principal_email = S.principal_email
        WHEN MATCHED THEN
          UPDATE SET
            principal_type = COALESCE(S.principal_type, T.principal_type),
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (principal_email, principal_type)
          VALUES (S.principal_email, S.principal_type)
        """
        job = self._client.query(sql)
        job.result()
        return job.num_dml_affected_rows or 0

    def run_update_raw_bindings_history_job(self, execution_id: str) -> int:
        """
        生のIAMバインディング履歴を記録します。

        Args:
            execution_id (str): このジョブ実行のユニークID。

        Returns:
            int: 挿入された行数。
        """
        sql = f"""
        INSERT INTO
          `{self._project_id}.{self._dataset_id}.iam_policy_bindings_raw_history` (
          execution_id, assessment_timestamp, scope, resource_type,
          resource_name, principal_type, principal_email, role
        )
        SELECT
          @execution_id, CURRENT_TIMESTAMP(), scope, resource_type,
          resource_name, principal_type, principal_email, role
        FROM `{self.iam_policy_permissions_table}`
        """
        params = [bigquery.ScalarQueryParameter("execution_id", "STRING", execution_id)]
        job = self._client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        )
        job.result()
        return job.num_dml_affected_rows or 0
