-- Build IAM permission matrix as pivot from history.
-- Replace `ea-yukihidemitsuoka2.iam_access_mgmt` before execution.

DECLARE role_cols STRING;

SET role_cols = (
  SELECT STRING_AGG(
    FORMAT(
      "MAX(IF(`IAMロール` = '%s', `ステータス`, NULL)) AS `%s`",
      REPLACE(role, "'", "\\'"),
      role
    ),
    ',\n  '
  )
  FROM (
    SELECT DISTINCT `IAMロール` AS role
    FROM `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_permission_history`
    WHERE `IAMロール` IS NOT NULL AND `IAMロール` != ''
  )
);

EXECUTE IMMEDIATE FORMAT(
  """
  CREATE OR REPLACE TABLE `ea-yukihidemitsuoka2.iam_access_mgmt.iam_permission_matrix` AS
  SELECT
    `リソース名`,
    `リソースID`,
    `プリンシパル`,
    `種別`,
    %s
  FROM (
    SELECT
      `リソース名`,
      `リソースID`,
      `プリンシパル`,
      `種別`,
      `IAMロール`,
      `ステータス`,
      `recorded_at`
    FROM `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_permission_history`
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY `リソースID`, `プリンシパル`, `IAMロール`
      ORDER BY `recorded_at` DESC
    ) = 1
  )
  GROUP BY 1,2,3,4
  """,
  COALESCE(role_cols, "CAST(NULL AS STRING) AS `NO_ROLE`")
);

CREATE OR REPLACE VIEW `ea-yukihidemitsuoka2.iam_access_mgmt.v_sheet_iam_permission_matrix` AS
SELECT *
FROM `ea-yukihidemitsuoka2.iam_access_mgmt.iam_permission_matrix`;
