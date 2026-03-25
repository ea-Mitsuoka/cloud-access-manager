/**
 * IAM request workflow bridge.
 *
 * Setup:
 * 1) Enable Advanced Service: BigQuery API.
 * 2) Set Script Properties:
 *    - BQ_PROJECT_ID
 *    - BQ_DATASET_ID
 *    - BQ_LOCATION (optional, default: asia-northeast1)
 *    - CLOUD_RUN_EXECUTE_URL
 *    - WEBHOOK_SHARED_SECRET (optional)
 * 3) Create installable triggers:
 *    - onFormSubmit (From spreadsheet, On form submit)
 *    - onEdit (From spreadsheet, On edit)
 */

const STATUS_APPROVED = 'APPROVED';
const STATUS_PENDING = 'PENDING';
const REQUEST_SHEET_NAME = 'requests_review';

function onFormSubmit(e) {
  const props = getProps_();
  const named = e.namedValues || {};

  const request = {
    request_id: Utilities.getUuid(),
    request_type: normalizeRequestType_(pick_(named, '申請種別')),
    principal_email: pick_(named, '対象プリンシパル'),
    resource_name: pick_(named, '対象リソース'),
    role: pick_(named, '付与・変更ロール'),
    reason: pick_(named, '申請理由・利用目的'),
    requester_email: pick_(named, '申請者メール'),
    approver_email: pick_(named, '承認者メール（または承認グループ）'),
    status: STATUS_PENDING,
    requested_at: new Date().toISOString(),
    ticket_ref: ''
  };

  validateRequest_(request);
  insertRequestToBigQuery_(props, request);
  appendReviewSheet_(request);
}

function onEdit(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== REQUEST_SHEET_NAME || range.getRow() === 1) {
    return;
  }

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const statusCol = header.indexOf('status') + 1;
  if (statusCol <= 0 || range.getColumn() !== statusCol) {
    return;
  }

  const newStatus = String(range.getValue() || '').trim().toUpperCase();
  if (newStatus !== STATUS_APPROVED) {
    return;
  }

  const row = sheet.getRange(range.getRow(), 1, 1, sheet.getLastColumn()).getValues()[0];
  const requestId = row[header.indexOf('request_id')];
  if (!requestId) {
    throw new Error('request_id not found in edited row');
  }

  updateApprovalInBigQuery_(getProps_(), requestId);
  callCloudRunExecute_(getProps_(), requestId);
}

function insertRequestToBigQuery_(props, request) {
  const sql = `
    INSERT INTO \`${props.projectId}.${props.datasetId}.iam_access_requests\`
    (
      request_id, request_type, principal_email, resource_name, role,
      reason, requester_email, approver_email, status, requested_at, ticket_ref,
      created_at, updated_at
    )
    VALUES (
      @request_id, @request_type, @principal_email, @resource_name, @role,
      @reason, @requester_email, @approver_email, @status, TIMESTAMP(@requested_at), @ticket_ref,
      CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
    )
  `;

  runQuery_(props, sql, [
    param_('request_id', 'STRING', request.request_id),
    param_('request_type', 'STRING', request.request_type),
    param_('principal_email', 'STRING', request.principal_email),
    param_('resource_name', 'STRING', request.resource_name),
    param_('role', 'STRING', request.role),
    param_('reason', 'STRING', request.reason),
    param_('requester_email', 'STRING', request.requester_email),
    param_('approver_email', 'STRING', request.approver_email),
    param_('status', 'STRING', request.status),
    param_('requested_at', 'STRING', request.requested_at),
    param_('ticket_ref', 'STRING', request.ticket_ref)
  ]);
}

function updateApprovalInBigQuery_(props, requestId) {
  const sql = `
    UPDATE \`${props.projectId}.${props.datasetId}.iam_access_requests\`
    SET status = 'APPROVED', approved_at = CURRENT_TIMESTAMP(), updated_at = CURRENT_TIMESTAMP()
    WHERE request_id = @request_id
  `;
  runQuery_(props, sql, [param_('request_id', 'STRING', requestId)]);
}

function callCloudRunExecute_(props, requestId) {
  const payload = JSON.stringify({ request_id: requestId });
  const headers = { 'Content-Type': 'application/json' };
  if (props.webhookSecret) {
    headers['X-Webhook-Token'] = props.webhookSecret;
  }

  const resp = UrlFetchApp.fetch(props.cloudRunUrl, {
    method: 'post',
    payload,
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers
  });

  const code = resp.getResponseCode();
  if (code >= 300) {
    throw new Error(`Cloud Run execute failed (${code}): ${resp.getContentText()}`);
  }
}

function appendReviewSheet_(request) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(REQUEST_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(REQUEST_SHEET_NAME);
    sheet.appendRow([
      'request_id', 'request_type', 'principal_email', 'resource_name', 'role',
      'reason', 'requester_email', 'approver_email', 'status', 'requested_at', 'ticket_ref'
    ]);
  }

  sheet.appendRow([
    request.request_id,
    request.request_type,
    request.principal_email,
    request.resource_name,
    request.role,
    request.reason,
    request.requester_email,
    request.approver_email,
    request.status,
    request.requested_at,
    request.ticket_ref
  ]);
}

function validateRequest_(request) {
  const required = ['request_type', 'principal_email', 'resource_name', 'role', 'requester_email'];
  required.forEach((k) => {
    if (!request[k]) {
      throw new Error(`required field is empty: ${k}`);
    }
  });
}

function getProps_() {
  const p = PropertiesService.getScriptProperties();
  return {
    projectId: p.getProperty('BQ_PROJECT_ID'),
    datasetId: p.getProperty('BQ_DATASET_ID'),
    location: p.getProperty('BQ_LOCATION') || 'asia-northeast1',
    cloudRunUrl: p.getProperty('CLOUD_RUN_EXECUTE_URL'),
    webhookSecret: p.getProperty('WEBHOOK_SHARED_SECRET') || ''
  };
}

function runQuery_(props, sql, queryParameters) {
  const request = {
    query: sql,
    useLegacySql: false,
    parameterMode: 'NAMED',
    queryParameters,
    location: props.location
  };
  const result = BigQuery.Jobs.query(request, props.projectId);
  if (!result.jobComplete && result.jobReference && result.jobReference.jobId) {
    waitForJob_(props, result.jobReference.jobId);
  }
  if (result.status && result.status.errorResult) {
    throw new Error(`BigQuery query failed: ${JSON.stringify(result.status.errorResult)}`);
  }
}

function waitForJob_(props, jobId) {
  for (let i = 0; i < 10; i += 1) {
    const status = BigQuery.Jobs.get(props.projectId, jobId, { location: props.location });
    if (status.status && status.status.state === 'DONE') {
      if (status.status.errorResult) {
        throw new Error(`BigQuery job failed: ${JSON.stringify(status.status.errorResult)}`);
      }
      return;
    }
    Utilities.sleep(500);
  }
  throw new Error(`BigQuery job timeout: ${jobId}`);
}

function param_(name, type, value) {
  return {
    name,
    parameterType: { type },
    parameterValue: { value }
  };
}

function pick_(namedValues, key) {
  const val = namedValues[key];
  return val && val.length ? String(val[0]).trim() : '';
}

function normalizeRequestType_(raw) {
  const v = String(raw || '').trim();
  if (v === '削除') return 'REVOKE';
  if (v === '変更') return 'CHANGE';
  return 'GRANT';
}
