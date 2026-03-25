-- Replace `your_project.your_dataset` before execution.
-- This query writes new issues for:
-- 1) APPROVED but permission is still missing
-- 2) REJECTED/CANCELLED but permission still exists
-- 3) Expired access that still exists

INSERT INTO `your_project.your_dataset.iam_reconciliation_issues` (
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
  FROM `your_project.your_dataset.iam_access_requests`
),
actual AS (
  SELECT
    principal_email,
    resource_name,
    role,
    TRUE AS exists_now
  FROM `your_project.your_dataset.iam_policy_permissions`
),
joined AS (
  SELECT
    r.*,
    IFNULL(a.exists_now, FALSE) AS exists_now
  FROM requests r
  LEFT JOIN actual a
    USING (principal_email, resource_name, role)
)
SELECT
  FORMAT('%s-%s-%s', request_id, issue_type, FORMAT_TIMESTAMP('%Y%m%d%H%M%S', CURRENT_TIMESTAMP())) AS issue_id,
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
      WHEN status = 'APPROVED' AND exists_now = FALSE THEN 'APPROVED_NOT_APPLIED'
      WHEN status IN ('REJECTED', 'CANCELLED') AND exists_now = TRUE THEN 'REJECTED_BUT_EXISTS'
      WHEN status = 'APPROVED' AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP() AND exists_now = TRUE THEN 'EXPIRED_BUT_EXISTS'
      ELSE NULL
    END AS issue_type,
    CASE
      WHEN status = 'APPROVED' AND exists_now = FALSE THEN 'HIGH'
      WHEN status IN ('REJECTED', 'CANCELLED') AND exists_now = TRUE THEN 'MEDIUM'
      WHEN status = 'APPROVED' AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP() AND exists_now = TRUE THEN 'HIGH'
      ELSE NULL
    END AS severity,
    status,
    exists_now,
    expires_at
  FROM joined
)
WHERE issue_type IS NOT NULL;
