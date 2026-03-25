-- Replace `ea-yukihidemitsuoka2.iam_access_mgmt` before execution.

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.iam_policy_permissions_history` (
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

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.iam_access_requests` (
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

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.iam_access_change_log` (
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

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.iam_access_request_history` (
  history_id STRING NOT NULL,
  request_id STRING NOT NULL,
  event_type STRING NOT NULL, -- REQUESTED / STATUS_CHANGED
  old_status STRING,
  new_status STRING NOT NULL,
  reason_snapshot STRING,
  request_type STRING,
  principal_email STRING,
  resource_name STRING,
  role STRING,
  requester_email STRING,
  approver_email STRING,
  acted_by STRING,
  actor_source STRING, -- FORM_SUBMIT / SHEET_EDIT / API
  event_at TIMESTAMP NOT NULL,
  details JSON
)
PARTITION BY DATE(event_at)
CLUSTER BY request_id, new_status, event_type;

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.iam_reconciliation_issues` (
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

CREATE TABLE IF NOT EXISTS `ea-yukihidemitsuoka2.iam_access_mgmt.pipeline_job_reports` (
  execution_id STRING NOT NULL,
  job_type STRING NOT NULL, -- RESOURCE_COLLECTION / GROUP_COLLECTION / ...
  result STRING NOT NULL, -- SUCCESS / FAILED_PERMISSION / FAILED
  error_code STRING,
  error_message STRING,
  hint STRING,
  counts JSON,
  details JSON,
  occurred_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(occurred_at)
CLUSTER BY job_type, result;
