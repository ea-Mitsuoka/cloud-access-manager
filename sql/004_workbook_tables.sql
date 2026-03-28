-- Workbook-compatible data model for IAM inventory management.
-- Replace `your_project.your_dataset` before execution.

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.principal_catalog` (
  principal_email STRING NOT NULL,
  principal_name STRING,
  principal_type STRING,
  note STRING,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY principal_type;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.google_groups` (
  group_email STRING NOT NULL,
  group_name STRING,
  description STRING,
  source STRING,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY group_email;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.google_group_membership_history` (
  execution_id STRING NOT NULL,
  assessed_at TIMESTAMP NOT NULL,
  group_email STRING NOT NULL,
  member_email STRING NOT NULL,
  member_display_name STRING,
  membership_type STRING,
  source STRING
)
PARTITION BY DATE(assessed_at)
CLUSTER BY group_email, member_email;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.gcp_resource_inventory_history` (
  execution_id STRING NOT NULL,
  assessed_at TIMESTAMP NOT NULL,
  resource_type STRING NOT NULL,
  resource_name STRING,
  resource_id STRING NOT NULL,
  parent_resource_id STRING,
  full_resource_path STRING,
  note STRING
)
PARTITION BY DATE(assessed_at)
CLUSTER BY resource_type, resource_id;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_status_master` (
  status_ja STRING NOT NULL,
  status_code STRING,
  description STRING,
  sort_order INT64,
  is_active BOOL NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_permission_bindings_history` (
  execution_id STRING NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  resource_name STRING,
  resource_id STRING,
  resource_full_path STRING,
  principal_email STRING NOT NULL,
  principal_type STRING,
  iam_role STRING NOT NULL,
  iam_condition STRING,
  ticket_ref STRING,
  request_reason STRING,
  status_ja STRING,
  approved_at TIMESTAMP,
  next_review_at DATE,
  approver STRING,
  request_id STRING,
  note STRING
)
PARTITION BY DATE(recorded_at)
CLUSTER BY resource_id, principal_email, iam_role;

-- Initial status master rows (idempotent via MERGE).
MERGE `your_project.your_dataset.iam_status_master` T
USING (
  SELECT '申請中' AS status_ja, 'PENDING' AS status_code, '利用者がアクセスを申請した状態' AS description, 10 AS sort_order UNION ALL
  SELECT '承認済', 'APPROVED', '承認は出たがまだプロビジョニング前', 60 UNION ALL
  SELECT '却下', 'REJECTED', '明確に拒否された状態', 50 UNION ALL
  SELECT '取消', 'CANCELLED', '申請者によってキャンセル', 55 UNION ALL
  SELECT 'プロビジョニング中', 'PROVISIONING', '付与処理中', 70 UNION ALL
  SELECT '有効', 'ACTIVE', '実際にアクセス可能な状態', 80 UNION ALL
  SELECT '無効化／削除済', 'REVOKED', 'アクセス取り消し完了', 120 UNION ALL
  SELECT '期限切れ', 'EXPIRED', 'TTL到達で自動無効化', 130 UNION ALL
  SELECT '実行失敗', 'REVOKE_FAILED', '剥奪失敗', 140
) S
ON T.status_ja = S.status_ja
WHEN MATCHED THEN
  UPDATE SET
    status_code = S.status_code,
    description = S.description,
    sort_order = S.sort_order,
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (status_ja, status_code, description, sort_order, is_active)
  VALUES (S.status_ja, S.status_code, S.description, S.sort_order, TRUE);
