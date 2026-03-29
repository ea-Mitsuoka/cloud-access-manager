-- Seed workbook-compatible tables from existing core tables.
-- Replace `your_project.your_dataset` before execution.

-- 1) principal catalog from current IAM snapshot
MERGE `your_project.your_dataset.principal_catalog` T
USING (
  SELECT DISTINCT
    principal_email,
    principal_type
  FROM `your_project.your_dataset.iam_policy_permissions`
  WHERE principal_email IS NOT NULL AND principal_email != ''
) S
ON T.principal_email = S.principal_email
WHEN MATCHED THEN
  UPDATE SET principal_type = COALESCE(S.principal_type, T.principal_type), updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (principal_email, principal_type)
  VALUES (S.principal_email, S.principal_type);

-- 2) IAM permission history from request + latest execution result
INSERT INTO `your_project.your_dataset.iam_permission_bindings_history` (
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
WITH req AS (
  SELECT
    r.request_id,
    r.requested_at,
    r.resource_name,
    REGEXP_EXTRACT(r.resource_name, r'^projects/(.+)$') AS resource_id,
    r.principal_email,
    COALESCE(p.principal_type, 'Unknown') AS principal_type,
    r.role AS iam_role,
    r.ticket_ref,
    r.reason AS request_reason,
    r.status,
    r.approved_at,
    r.expires_at,
    r.approver_email
  FROM `your_project.your_dataset.iam_access_requests` r
  LEFT JOIN (
    SELECT principal_email, ANY_VALUE(principal_type) AS principal_type
    FROM `your_project.your_dataset.iam_policy_permissions`
    GROUP BY principal_email
  ) p USING (principal_email)
),
latest_exec AS (
  SELECT
    request_id,
    ARRAY_AGG(STRUCT(result, executed_at) ORDER BY executed_at DESC LIMIT 1)[OFFSET(0)] AS ex
  FROM `your_project.your_dataset.iam_access_change_log`
  GROUP BY request_id
)
SELECT
  COALESCE(CAST(FARM_FINGERPRINT(CONCAT(req.request_id, ':seed')) AS STRING), GENERATE_UUID()) AS execution_id,
  CURRENT_TIMESTAMP() AS recorded_at,
  req.resource_name,
  req.resource_id,
  req.principal_email,
  req.principal_type,
  req.iam_role,
  NULL AS iam_condition,
  req.ticket_ref,
  req.request_reason,
  CASE
    WHEN req.status = 'APPROVED' AND ex.ex.result = 'SUCCESS' THEN '有効'
    WHEN req.status = 'APPROVED' AND ex.ex.result IN ('FAILED', 'SKIPPED') THEN 'プロビジョニング中'
    WHEN req.status = 'APPROVED' THEN '承認済'
    WHEN req.status = 'REJECTED' THEN '却下'
    WHEN req.status = 'CANCELLED' THEN '無効化／削除済'
    ELSE '申請中'
  END AS status_ja,
  req.approved_at,
  CAST(req.expires_at AS DATE) AS next_review_at,
  req.approver_email AS approver,
  req.request_id,
  'seed from iam_access_requests' AS note
FROM req
LEFT JOIN latest_exec ex USING (request_id)
WHERE req.request_id IS NOT NULL;
