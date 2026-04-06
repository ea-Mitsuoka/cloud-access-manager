-- Replace `your_project.your_dataset` before execution.

CREATE OR REPLACE VIEW `your_project.your_dataset.v_iam_request_execution_latest` AS
WITH latest_execution AS (
  SELECT
    request_id,
    ARRAY_AGG(
      STRUCT(
        execution_id,
        action,
        target,
        before_hash,
        after_hash,
        result,
        error_code,
        error_message,
        executed_by,
        executed_at,
        details
      )
      ORDER BY executed_at DESC
      LIMIT 1
    )[OFFSET(0)] AS exec
  FROM `your_project.your_dataset.iam_access_change_log`
  GROUP BY request_id
)
SELECT
  r.request_id,
  r.request_group_id,
  r.request_type,
  r.principal_email,
  r.resource_name,
  r.role,
  r.reason,
  r.expires_at,
  r.requester_email,
  r.approver_email,
  r.status,
  r.requested_at,
  r.approved_at,
  r.ticket_ref,
  e.exec.execution_id AS latest_execution_id,
  e.exec.result AS latest_execution_result,
  e.exec.executed_at AS latest_executed_at,
  e.exec.error_code AS latest_error_code,
  e.exec.error_message AS latest_error_message
FROM `your_project.your_dataset.iam_access_requests` r
LEFT JOIN latest_execution e USING (request_id);

CREATE OR REPLACE VIEW `your_project.your_dataset.v_iam_request_approval_history` AS
SELECT
  history_id,
  request_id,
  request_group_id,
  event_type,
  old_status,
  new_status,
  reason_snapshot AS reason,
  request_type,
  principal_email,
  resource_name,
  role,
  requester_email,
  approver_email,
  acted_by,
  actor_source,
  event_at,
  details
FROM `your_project.your_dataset.iam_access_request_history`;

CREATE OR REPLACE VIEW `your_project.your_dataset.v_iam_inventory_with_requests` AS
SELECT
  p.resource_type,
  p.resource_name,
  p.principal_type,
  p.principal_email,
  p.role,
  r.request_id,
  r.request_group_id,
  r.status AS request_status,
  r.requested_at,
  r.approved_at,
  r.ticket_ref,
  l.latest_execution_result,
  l.latest_executed_at
FROM `your_project.your_dataset.iam_policy_permissions` p
LEFT JOIN (
  SELECT * FROM `your_project.your_dataset.v_iam_request_execution_latest`
  QUALIFY ROW_NUMBER() OVER(PARTITION BY principal_email, role, resource_name ORDER BY requested_at DESC) = 1
) l
  ON p.resource_name = l.resource_name
  AND p.principal_email = l.principal_email
  AND p.role = l.role
LEFT JOIN `your_project.your_dataset.iam_access_requests` r
  ON l.request_id = r.request_id;
