-- Appends the current state of IAM policies to the history table.
-- This script should be run periodically to build a history of IAM bindings over time.

-- Replace `your_project.your_dataset` before execution.
-- The @execution_id parameter should be passed in by the calling process.

INSERT INTO `your_project.your_dataset.iam_permission_bindings_history` (
  execution_id,
  recorded_at,
  resource_name,
  resource_id,
  resource_full_path,
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
  
  -- From iam_policy_permissions (current state)
  p.resource_name,
  p.resource_id,
  p.full_resource_path,
  p.principal_email,
  p.principal_type,
  p.role AS iam_role,
  p.iam_condition,
  
  -- Enriched from iam_access_requests
  req.ticket_ref,
  req.reason AS request_reason,
  status_map.status_ja,
  req.approved_at,
  req.expires_at AS next_review_at, -- Assuming expires_at is the next review date
  req.approver_email AS approver,
  req.request_id,
  
  'Snapshot from iam_policy_permissions' AS note

FROM
  `your_project.your_dataset.iam_policy_permissions` AS p
LEFT JOIN
  -- Join with the latest request information for the given permission
  `your_project.your_dataset.v_iam_request_execution_latest` AS req
  ON p.principal_email = req.principal_email
  AND p.role = req.role
  AND p.resource_name = req.resource_name -- This join condition might need to be more robust
LEFT JOIN
  `your_project.your_dataset.iam_status_master` AS status_map
  ON req.status = status_map.status_code;
