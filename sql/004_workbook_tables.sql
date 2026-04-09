-- Workbook-compatible data model for IAM inventory management.
-- Replace `your_project.your_dataset` before execution.

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.principal_catalog` (
  principal_email STRING NOT NULL,
  principal_name STRING,
  principal_type STRING,
  principal_status STRING DEFAULT 'ACTIVE' NOT NULL,
  deactivated_at TIMESTAMP,
  note STRING,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
)
CLUSTER BY principal_type;

ALTER TABLE `your_project.your_dataset.principal_catalog`
ADD COLUMN IF NOT EXISTS principal_status STRING;

ALTER TABLE `your_project.your_dataset.principal_catalog`
ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP;

UPDATE `your_project.your_dataset.principal_catalog`
SET principal_status = 'ACTIVE'
WHERE principal_status IS NULL;

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
  is_active BOOL DEFAULT TRUE NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
);

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_permission_bindings_history` (
  execution_id STRING NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  resource_name STRING,
  resource_id STRING,
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
  request_group_id STRING,
  note STRING
)
PARTITION BY DATE(recorded_at)
CLUSTER BY resource_id, principal_email, iam_role;

ALTER TABLE `your_project.your_dataset.iam_permission_bindings_history`
ADD COLUMN IF NOT EXISTS request_group_id STRING;

UPDATE `your_project.your_dataset.iam_permission_bindings_history`
SET request_group_id = request_id
WHERE request_group_id IS NULL;

-- Initial status master rows (idempotent via MERGE).
MERGE `your_project.your_dataset.iam_status_master` T
USING (
  SELECT '申請中' AS status_ja, 'PENDING' AS status_code, '申請直後の承認待ち状態' AS description, 10 AS sort_order UNION ALL
  SELECT '承認済' AS status_ja, 'APPROVED' AS status_code, '承認され権限が付与された状態' AS description, 20 AS sort_order UNION ALL
  SELECT '却下' AS status_ja, 'REJECTED' AS status_code, '承認者により拒否された状態' AS description, 30 AS sort_order UNION ALL
  SELECT '取消' AS status_ja, 'CANCELLED' AS status_code, '申請者により取り消された状態' AS description, 40 AS sort_order UNION ALL
  SELECT '削除済' AS status_ja, 'REVOKED' AS status_code, '期間満了等で自動剥奪された状態' AS description, 50 AS sort_order UNION ALL
  SELECT '削除済(手動)' AS status_ja, 'REVOKED_ALREADY_GONE' AS status_code, '剥奪前にGCPから手動削除されていた状態' AS description, 60 AS sort_order UNION ALL
  SELECT '剥奪失敗' AS status_ja, 'REVOKE_FAILED' AS status_code, '自動剥奪に失敗した状態' AS description, 70 AS sort_order
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

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_role_master` (
  role_id STRING NOT NULL,
  role_name_ja STRING,
  is_auto_translated BOOL DEFAULT FALSE,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
)
CLUSTER BY role_id;
