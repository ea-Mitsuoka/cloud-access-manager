-- Replace `ea-yukihidemitsuoka2.iam_access_mgmt` before execution.

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
