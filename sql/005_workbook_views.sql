-- Workbook-compatible sheet views.
-- Replace `your_project.your_dataset` before execution.

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_principal` AS
SELECT
  principal_email AS `プリンシパル（メールアドレス）`,
  principal_name AS `プリンシパル名`,
  principal_type AS `種別`,
  note AS `備考`
FROM `your_project.your_dataset.principal_catalog`;

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_group_members` AS
WITH latest_exec AS (
  SELECT execution_id
  FROM `your_project.your_dataset.google_group_membership_history`
  ORDER BY assessed_at DESC
  LIMIT 1
)
SELECT
  group_email AS `グループEmail`,
  member_email AS `メンバーEmail`,
  member_display_name AS `メンバー表示名`
FROM `your_project.your_dataset.google_group_membership_history`
WHERE execution_id = (SELECT execution_id FROM latest_exec);

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_group` AS
SELECT
  group_email AS `グループEmail`,
  group_name AS `グループ名`,
  description AS `説明`
FROM `your_project.your_dataset.google_groups`;

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_resource` AS
WITH latest_exec AS (
  SELECT execution_id
  FROM `your_project.your_dataset.gcp_resource_inventory_history`
  ORDER BY assessed_at DESC
  LIMIT 1
)
SELECT
  resource_type AS `リソースタイプ`,
  resource_name AS `リソース名`,
  resource_id AS `リソースID`,
  parent_resource_id AS `親リソースID`,
  note AS `備考`
FROM `your_project.your_dataset.gcp_resource_inventory_history`
WHERE execution_id = (SELECT execution_id FROM latest_exec);

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_iam_role` AS
WITH catalog_roles AS (
  SELECT DISTINCT
    CASE
      WHEN STARTS_WITH(role, 'roles/') THEN REGEXP_EXTRACT(role, r'roles/([^/]+)$')
      WHEN REGEXP_CONTAINS(role, r'/roles/') THEN REGEXP_EXTRACT(role, r'/roles/([^/]+)$')
      ELSE role
    END AS role_name,
    CASE
      WHEN STARTS_WITH(role, 'roles/') THEN '事前定義'
      ELSE 'カスタム'
    END AS role_type
  FROM `your_project.your_dataset.iam_policy_permissions`
)
SELECT
  role_name AS `ロール名`,
  role_type AS `種別`,
  CAST(NULL AS STRING) AS `説明`
FROM catalog_roles
WHERE role_name IS NOT NULL;

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_iam_permission_history` AS
WITH
  LatestChangeLog AS (
    SELECT
      request_id,
      ARRAY_AGG(STRUCT(action, result) ORDER BY executed_at DESC LIMIT 1)[OFFSET(0)] AS latest_exec
    FROM `your_project.your_dataset.iam_access_change_log`
    GROUP BY request_id
  ),
  LatestSnapshot AS (
    SELECT execution_id
    FROM `your_project.your_dataset.iam_permission_bindings_history`
    ORDER BY recorded_at DESC
    LIMIT 1
  )
SELECT
  p.resource_name AS `リソース名`,
  p.resource_id AS `リソースID`,
  p.resource_full_path AS `リソースのフルパス`,
  p.principal_email AS `プリンシパル`,
  p.principal_type AS `種別`,
  p.iam_role AS `IAMロール`,
  p.iam_condition AS `IAM Condition`,
  p.ticket_ref AS `申請チケット番号`,
  p.request_reason AS `申請理由・用途`,
  COALESCE(sm.status_ja, p.status_ja) AS `ステータス`,
  p.approved_at AS `承認日`,
  p.next_review_at AS `次回レビュー日`,
  p.approver AS `承認者`,
  p.request_id AS `request_id`,
  p.recorded_at AS `recorded_at`,
  r.expires_at AS `利用期限`,
  r.status AS `リクエストステータス`,
  lcl.latest_exec.action AS `最終実行アクション`,
  lcl.latest_exec.result AS `最終実行結果`
FROM `your_project.your_dataset.iam_permission_bindings_history` AS p
LEFT JOIN `your_project.your_dataset.iam_access_requests` AS r
  ON p.request_id = r.request_id
LEFT JOIN `your_project.your_dataset.iam_status_master` AS sm
  ON r.status = sm.status_code
LEFT JOIN LatestChangeLog AS lcl
  ON p.request_id = lcl.request_id
WHERE p.execution_id = (SELECT execution_id FROM LatestSnapshot);

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_status` AS
SELECT
  status_ja AS `ステータス`,
  status_code AS `status`,
  description AS `説明`
FROM `your_project.your_dataset.iam_status_master`
WHERE is_active
ORDER BY sort_order;

CREATE OR REPLACE VIEW `your_project.your_dataset.v_sheet_custom_role` AS
SELECT
  `ロール名` AS `カスタムロール名`,
  CAST(NULL AS STRING) AS `作成者`,
  CAST(NULL AS STRING) AS `権限`
FROM `your_project.your_dataset.v_sheet_iam_role`
WHERE `種別` = 'カスタム';
