-- Workbook-compatible sheet views.
-- Replace `ea-yukihidemitsuoka2.iam_access_mgmt` before execution.

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_principal` AS
SELECT
  principal_email AS `プリンシパル（メールアドレス）`,
  principal_name AS `プリンシパル名`,
  principal_type AS `種別`,
  note AS `備考`
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.principal_catalog`;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_group_members` AS
WITH latest AS (
  SELECT *
  FROM `ea-yukihidemitsuoka2.iam_access_mgmt.google_group_membership_history`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY group_email, member_email ORDER BY assessed_at DESC, execution_id DESC) = 1
)
SELECT
  group_email AS `グループEmail`,
  member_email AS `メンバーEmail`,
  member_display_name AS `メンバー表示名`
FROM latest;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_group` AS
SELECT
  group_email AS `グループEmail`,
  group_name AS `グループ名`,
  description AS `説明`
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.google_groups`;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_resource` AS
WITH latest AS (
  SELECT *
  FROM `ea-yukihidemitsuoka2.iam_access_mgmt.gcp_resource_inventory_history`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_id ORDER BY assessed_at DESC, execution_id DESC) = 1
)
SELECT
  resource_type AS `リソースタイプ`,
  resource_name AS `リソース名`,
  resource_id AS `リソースID`,
  parent_resource_id AS `親リソースID`,
  note AS `備考`
FROM latest;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_role` AS
WITH catalog_roles AS (
  SELECT DISTINCT
    CASE
      WHEN STARTS_WITH(iam_role, 'roles/') THEN REGEXP_EXTRACT(iam_role, r'roles/([^/]+)$')
      WHEN REGEXP_CONTAINS(iam_role, r'/roles/') THEN REGEXP_EXTRACT(iam_role, r'/roles/([^/]+)$')
      ELSE iam_role
    END AS role_name,
    CASE
      WHEN STARTS_WITH(iam_role, 'roles/') THEN '事前定義'
      ELSE 'カスタム'
    END AS role_type
  FROM `ea-yukihidemitsuoka2.iam_access_mgmt.iam_permission_bindings_history`
)
SELECT
  role_name AS `ロール名`,
  role_type AS `種別`,
  CAST(NULL AS STRING) AS `説明`
FROM catalog_roles
WHERE role_name IS NOT NULL;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_permission_history` AS
SELECT
  resource_name AS `リソース名`,
  resource_id AS `リソースID`,
  resource_full_path AS `リソースのフルパス`,
  principal_email AS `プリンシパル`,
  principal_type AS `種別`,
  iam_role AS `IAMロール`,
  iam_condition AS `IAM Condition`,
  ticket_ref AS `申請チケット番号`,
  request_reason AS `申請理由・用途`,
  status_ja AS `ステータス`,
  approved_at AS `承認日`,
  next_review_at AS `次回レビュー日`,
  approver AS `承認者`,
  request_id AS `request_id`,
  recorded_at AS `recorded_at`
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.iam_permission_bindings_history`;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_status` AS
SELECT
  status_ja AS `ステータス`,
  status_code AS `status`,
  description AS `説明`
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.iam_status_master`
WHERE is_active
ORDER BY sort_order;

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_custom_role` AS
SELECT
  `ロール名` AS `カスタムロール名`,
  CAST(NULL AS STRING) AS `作成者`,
  CAST(NULL AS STRING) AS `権限`
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_role`
WHERE `種別` = 'カスタム';
