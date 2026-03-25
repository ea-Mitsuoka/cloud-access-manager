-- Replace `your_project.your_dataset` before execution.

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_policy_permissions_history` (
  execution_id STRING NOT NULL,
  assessment_timestamp TIMESTAMP NOT NULL,
  scope STRING,
  resource_type STRING,
  resource_name STRING,
  principal_type STRING,
  principal_email STRING,
  role STRING
)
PARTITION BY DATE(assessment_timestamp)
CLUSTER BY resource_type, principal_email, role;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_access_requests` (
  request_id STRING NOT NULL,
  request_type STRING NOT NULL, -- GRANT / REVOKE / CHANGE
  principal_email STRING NOT NULL,
  resource_name STRING NOT NULL,
  role STRING NOT NULL,
  reason STRING,
  expires_at TIMESTAMP,
  requester_email STRING NOT NULL,
  approver_email STRING,
  status STRING NOT NULL, -- PENDING / APPROVED / REJECTED / CANCELLED
  requested_at TIMESTAMP NOT NULL,
  approved_at TIMESTAMP,
  ticket_ref STRING,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(requested_at)
CLUSTER BY status, principal_email, role;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_access_change_log` (
  execution_id STRING NOT NULL,
  request_id STRING NOT NULL,
  action STRING NOT NULL, -- GRANT / REVOKE
  target STRING NOT NULL,
  before_hash STRING,
  after_hash STRING,
  result STRING NOT NULL, -- SUCCESS / FAILED / SKIPPED
  error_code STRING,
  error_message STRING,
  executed_by STRING,
  executed_at TIMESTAMP NOT NULL,
  details JSON
)
PARTITION BY DATE(executed_at)
CLUSTER BY request_id, result;

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_reconciliation_issues` (
  issue_id STRING NOT NULL,
  issue_type STRING NOT NULL,
  request_id STRING,
  principal_email STRING,
  resource_name STRING,
  role STRING,
  detected_at TIMESTAMP NOT NULL,
  severity STRING NOT NULL,
  status STRING NOT NULL,
  details JSON
)
PARTITION BY DATE(detected_at)
CLUSTER BY issue_type, status, severity;
