-- Replace `your_project.your_dataset` before execution.

CREATE TABLE IF NOT EXISTS `your_project.your_dataset.iam_access_request_history` (
  history_id STRING NOT NULL,
  request_id STRING NOT NULL,
  request_group_id STRING,
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

-- Backward-compatible migrations for existing environments.
ALTER TABLE `your_project.your_dataset.iam_access_requests`
ADD COLUMN IF NOT EXISTS request_group_id STRING;

ALTER TABLE `your_project.your_dataset.iam_access_request_history`
ADD COLUMN IF NOT EXISTS request_group_id STRING;

UPDATE `your_project.your_dataset.iam_access_requests`
SET request_group_id = request_id
WHERE request_group_id IS NULL;

UPDATE `your_project.your_dataset.iam_access_request_history`
SET request_group_id = request_id
WHERE request_group_id IS NULL;
