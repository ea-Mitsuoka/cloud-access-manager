/**
 * IAM request workflow bridge.
 *
 * Setup:
 * 1) Enable Advanced Service: BigQuery API.
 * 2) Set Script Properties:
 *    - BQ_PROJECT_ID
 *    - BQ_DATASET_ID
 *    - BQ_LOCATION
 *    - CLOUD_RUN_EXECUTE_URL
 *    - WEBHOOK_SHARED_SECRET (optional)
 *    - GEMINI_API_KEY (GeminiRoleAdvisor.gs を使う場合)
 * 3) Create installable triggers:
 *    - onFormSubmit (From spreadsheet, On form submit)
 *    - onEdit (From spreadsheet, On edit)
 */

const STATUS_APPROVED = 'APPROVED';
const STATUS_PENDING = 'PENDING';
const REQUEST_SHEET_NAME = 'requests_review';
const HISTORY_SHEET_NAME = 'IAM権限設定履歴';
const MATRIX_SHEET_NAME = 'IAM権限設定マトリクス';
const FIELD_REQUEST_TYPE = '申請種別';
const FIELD_PRINCIPAL = '対象プリンシパル';
const FIELD_RESOURCE = '対象リソース';
const FIELD_ROLE = '付与・変更ロール';
const FIELD_REASON = '申請理由・利用目的';
const FIELD_REASON_ALT = '利用目的';
const FIELD_REQUESTER = '申請者メール';
const FIELD_APPROVER = '承認者メール（または承認グループ）';
const COL_EXEC_RESULT = '実行結果';
const COL_FINAL_REFLECT = '最終反映確認';
const COL_LAST_CHECKED = '最終確認時刻';
const EVENT_REQUESTED = 'REQUESTED';
const EVENT_STATUS_CHANGED = 'STATUS_CHANGED';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('棚卸し')
    .addItem('申請反映ステータス更新', 'menuRefreshRequestReviewStatus_')
    .addItem('マトリクス更新', 'menuRefreshIamMatrixPivot_')
    .addToUi();
}

function onFormSubmit(e) {
  const props = getProps_();
  const named = e.namedValues || {};
  const rawRequestType = pick_(named, FIELD_REQUEST_TYPE);
  const isEmergency = rawRequestType === '緊急付与' || rawRequestType.indexOf('緊急') !== -1 || rawRequestType.toUpperCase().indexOf('EMERGENCY') !== -1;
  const reason = (isEmergency ? '[緊急] ' : '') + pickFirst_(named, [FIELD_REASON, FIELD_REASON_ALT]);

  const request = {
    request_id: Utilities.getUuid(),
    request_type: normalizeRequestType_(rawRequestType),
    principal_email: pick_(named, FIELD_PRINCIPAL),
    resource_name: pick_(named, FIELD_RESOURCE),
    role: pick_(named, FIELD_ROLE),
    reason: reason,
    requester_email: pick_(named, FIELD_REQUESTER),
    approver_email: pick_(named, FIELD_APPROVER),
    status: STATUS_PENDING,
    requested_at: new Date().toISOString(),
    ticket_ref: ''
  };
  validateRequest_(request);
  insertRequestToBigQuery_(props, request);
  insertRequestHistoryEvent_(props, {
    request_id: request.request_id,
    event_type: EVENT_REQUESTED,
    old_status: '',
    new_status: request.status,
    reason_snapshot: request.reason,
    request_type: request.request_type,
    principal_email: request.principal_email,
    resource_name: request.resource_name,
    role: request.role,
    requester_email: request.requester_email,
    approver_email: request.approver_email,
    acted_by: request.requester_email || getActorEmail_(),
    actor_source: 'FORM_SUBMIT',
    details_json: JSON.stringify({ source: 'google_form' })
  });
  appendReviewSheet_(request);

  // 緊急アクセスの場合は即時承認フローへ回す
  if (isEmergency) {
    updateStatusInBigQuery_(props, request.request_id, STATUS_APPROVED);
    insertRequestHistoryEvent_(props, {
      request_id: request.request_id,
      event_type: EVENT_STATUS_CHANGED,
      old_status: STATUS_PENDING,
      new_status: STATUS_APPROVED,
      reason_snapshot: request.reason,
      request_type: request.request_type,
      principal_email: request.principal_email,
      resource_name: request.resource_name,
      role: request.role,
      requester_email: request.requester_email,
      approver_email: request.approver_email,
      acted_by: 'SYSTEM_AUTO_APPROVE',
      actor_source: 'SYSTEM',
      details_json: JSON.stringify({ note: 'Break-glass auto approval' })
    });
    callCloudRunExecute_(props, request.request_id);
    refreshRequestReviewStatusForRequestIds_([request.request_id]);
  }
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

  const props = getProps_();
  const newStatusRaw = String(range.getValue() || '').trim();
  const normalized = normalizeStatus_(newStatusRaw);

  const row = sheet.getRange(range.getRow(), 1, 1, sheet.getLastColumn()).getValues()[0];
  const requestId = row[header.indexOf('request_id')];
  if (!requestId) {
    throw new Error('request_id not found in edited row');
  }

  const snapshot = getRequestSnapshot_(props, requestId);
  const prevStatus = snapshot && snapshot.status ? String(snapshot.status) : '';
  if (!prevStatus) {
    throw new Error(`request not found in BigQuery: ${requestId}`);
  }
  if (prevStatus === normalized) {
    return;
  }

  updateStatusInBigQuery_(props, requestId, normalized);
  insertRequestHistoryEvent_(props, {
    request_id: String(requestId),
    event_type: EVENT_STATUS_CHANGED,
    old_status: prevStatus,
    new_status: normalized,
    reason_snapshot: snapshot.reason || '',
    request_type: snapshot.request_type || '',
    principal_email: snapshot.principal_email || '',
    resource_name: snapshot.resource_name || '',
    role: snapshot.role || '',
    requester_email: snapshot.requester_email || '',
    approver_email: snapshot.approver_email || '',
    acted_by: getActorEmail_(),
    actor_source: 'SHEET_EDIT',
    details_json: JSON.stringify({
      sheet: REQUEST_SHEET_NAME,
      edited_status_raw: newStatusRaw
    })
  });
  if (normalized === STATUS_APPROVED) {
    callCloudRunExecute_(props, requestId);
  }
  refreshRequestReviewStatusForRequestIds_([String(requestId)]);
}

function insertRequestToBigQuery_(props, request) {
  const sql = `
    INSERT INTO `${props.projectId}.${props.datasetId}.iam_access_requests`
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

function updateStatusInBigQuery_(props, requestId, normalizedStatus) {
  const statusExpr = normalizedStatus === STATUS_APPROVED
    ? "status = @status, approved_at = CURRENT_TIMESTAMP(), updated_at = CURRENT_TIMESTAMP()"
    : "status = @status, updated_at = CURRENT_TIMESTAMP()";

  const sql = `
    UPDATE `${props.projectId}.${props.datasetId}.iam_access_requests`
    SET ${statusExpr}
    WHERE request_id = @request_id
  `;
  runQuery_(props, sql, [
    param_('request_id', 'STRING', requestId),
    param_('status', 'STRING', normalizedStatus)
  ]);
}

function getRequestSnapshot_(props, requestId) {
  const sql = `
    SELECT
      request_id,
      request_type,
      principal_email,
      resource_name,
      role,
      reason,
      requester_email,
      approver_email,
      status
    FROM `${props.projectId}.${props.datasetId}.iam_access_requests`
    WHERE request_id = @request_id
    LIMIT 1
  `;
  const rows = runSelectQuery_(props, sql, [param_('request_id', 'STRING', String(requestId))]);
  return rows.length ? rows[0] : null;
}

function insertRequestHistoryEvent_(props, event) {
  const sql = `
    INSERT INTO `${props.projectId}.${props.datasetId}.iam_access_request_history`
    (
      history_id,
      request_id,
      event_type,
      old_status,
      new_status,
      reason_snapshot,
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
    )
    VALUES (
      @history_id,
      @request_id,
      @event_type,
      @old_status,
      @new_status,
      @reason_snapshot,
      @request_type,
      @principal_email,
      @resource_name,
      @role,
      @requester_email,
      @approver_email,
      @acted_by,
      @actor_source,
      CURRENT_TIMESTAMP(),
      PARSE_JSON(@details_json)
    )
  `;
  runQuery_(props, sql, [
    param_('history_id', 'STRING', Utilities.getUuid()),
    param_('request_id', 'STRING', String(event.request_id || '')),
    param_('event_type', 'STRING', String(event.event_type || '')),
    param_('old_status', 'STRING', String(event.old_status || '')),
    param_('new_status', 'STRING', String(event.new_status || '')),
    param_('reason_snapshot', 'STRING', String(event.reason_snapshot || '')),
    param_('request_type', 'STRING', String(event.request_type || '')),
    param_('principal_email', 'STRING', String(event.principal_email || '')),
    param_('resource_name', 'STRING', String(event.resource_name || '')),
    param_('role', 'STRING', String(event.role || '')),
    param_('requester_email', 'STRING', String(event.requester_email || '')),
    param_('approver_email', 'STRING', String(event.approver_email || '')),
    param_('acted_by', 'STRING', String(event.acted_by || 'unknown')),
    param_('actor_source', 'STRING', String(event.actor_source || 'UNKNOWN')),
    param_('details_json', 'STRING', String(event.details_json || '{}'))
  ]);
}

function callCloudRunExecute_(props, requestId) {
  const payload = JSON.stringify({ request_id: requestId });
  const headers = { 'Content-Type': 'application/json' };
  if (props.webhookSecret) {
    headers['X-Webhook-Token'] = props.webhookSecret;
  }

  const options = {
    method: 'post',
    payload,
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers
  };

  const maxRetries = 3;
  for (let i = 0; i < maxRetries; i += 1) {
    try {
      const resp = UrlFetchApp.fetch(props.cloudRunUrl, options);
      const code = resp.getResponseCode();
      if (code >= 300) {
        throw new Error(`Cloud Run execute failed (${code}): ${resp.getContentText()}`);
      }
      return; // 成功した場合はループを抜ける
    } catch (err) {
      if (i === maxRetries - 1) {
        throw err; // 最大リトライ回数に達した場合はエラーを投げる
      }
      Utilities.sleep(1000 * (i + 1)); // 失敗時は待機 (1秒, 2秒...)
    }
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

  ensureRequestReviewColumns_(sheet);

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
  const required = ['request_type', 'principal_email', 'resource_name', 'role', 'reason', 'requester_email'];
  required.forEach((k) => {
    if (!request[k]) {
      throw new Error(`required field is empty: ${k}`);
    }
  });
}

function getProps_() {
  const p = PropertiesService.getScriptProperties();
  const props = {
    projectId: p.getProperty('BQ_PROJECT_ID'),
    datasetId: p.getProperty('BQ_DATASET_ID'),
    location: p.getProperty('BQ_LOCATION'),
    cloudRunUrl: p.getProperty('CLOUD_RUN_EXECUTE_URL'),
    webhookSecret: p.getProperty('WEBHOOK_SHARED_SECRET') || ''
  };
  validateProps_(props);
  return props;
}

function validateProps_(props) {
  const required = ['projectId', 'datasetId', 'location', 'cloudRunUrl'];
  required.forEach((k) => {
    if (!props[k]) {
      throw new Error(`missing script property: ${k}`);
    }
  });
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

function pickFirst_(namedValues, keys) {
  for (let i = 0; i < keys.length; i += 1) {
    const v = pick_(namedValues, keys[i]);
    if (v) return v;
  }
  return '';
}

function normalizeRequestType_(raw) {
  const v = String(raw || '').trim();
  
  // 推奨案のラジオボタン選択肢に完全対応
  if (v === '新規付与') return 'GRANT';
  if (v === '変更') return 'CHANGE';
  if (v === '削除') return 'REVOKE';
  if (v === '緊急付与' || v.indexOf('緊急') !== -1) return 'GRANT';
  
  // 未知の入力（表記ゆれ等）に対する安全なフォールバック
  return 'GRANT';
}

function normalizeStatus_(raw) {
  const v = String(raw || '').trim();
  if (!v) return STATUS_PENDING;
  const map = {
    '承認済': 'APPROVED',
    '承認済み': 'APPROVED',
    'APPROVED': 'APPROVED',
    '申請中': 'PENDING',
    'PENDING': 'PENDING',
    '却下': 'REJECTED',
    'REJECTED': 'REJECTED',
    '取消': 'CANCELLED',
    'キャンセル': 'CANCELLED',
    'CANCELLED': 'CANCELLED'
  };
  return map[v] || v;
}

function getActorEmail_() {
  try {
    return Session.getActiveUser().getEmail() || 'unknown';
  } catch (err) {
    return 'unknown';
  }
}

/**
 * Build pivot table in `IAM権限設定マトリクス` from raw rows in `IAM権限設定履歴`.
 * Non-engineers can refresh this from Apps Script editor.
 */
function refreshIamMatrixPivotFromHistory() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const history = ss.getSheetByName(HISTORY_SHEET_NAME);
  if (!history) {
    throw new Error(`sheet not found: ${HISTORY_SHEET_NAME}`);
  }

  const lastRow = history.getLastRow();
  const lastCol = history.getLastColumn();
  if (lastRow < 2 || lastCol < 1) {
    throw new Error(`${HISTORY_SHEET_NAME} has no data rows`);
  }

  const header = history.getRange(1, 1, 1, lastCol).getValues()[0];
  const idx = indexMap_(header);
  const required = ['リソース名', 'リソースID', 'プリンシパル', '種別', 'IAMロール', 'ステータス'];
  required.forEach((name) => {
    if (!idx[name]) {
      throw new Error(`required column not found in ${HISTORY_SHEET_NAME}: ${name}`);
    }
  });

  let matrix = ss.getSheetByName(MATRIX_SHEET_NAME);
  if (!matrix) {
    matrix = ss.insertSheet(MATRIX_SHEET_NAME);
  } else {
    matrix.clear();
  }

  const sourceRange = history.getRange(1, 1, lastRow, lastCol);
  matrix.getRange(1, 1).setValue('IAM権限設定履歴ベースのピボット（Spreadsheet標準機能）');
  const pivot = matrix.getRange(3, 1).createPivotTable(sourceRange);

  pivot.addRowGroup(idx['リソース名']);
  pivot.addRowGroup(idx['リソースID']);
  pivot.addRowGroup(idx['プリンシパル']);
  pivot.addRowGroup(idx['種別']);
  pivot.addColumnGroup(idx['IAMロール']);
  pivot.addPivotValue(idx['ステータス'], SpreadsheetApp.PivotTableSummarizeFunction.COUNTA);
}

function menuRefreshIamMatrixPivot_() {
  try {
    refreshIamMatrixPivotFromHistory();
    SpreadsheetApp.getActiveSpreadsheet().toast('IAM権限設定マトリクスを更新しました。', '棚卸し', 5);
  } catch (err) {
    SpreadsheetApp.getUi().alert(`マトリクス更新に失敗しました: ${err.message}`);
    throw err;
  }
}

function menuRefreshRequestReviewStatus_() {
  try {
    refreshRequestReviewStatus_();
    SpreadsheetApp.getActiveSpreadsheet().toast('requests_review の実行反映ステータスを更新しました。', '棚卸し', 5);
  } catch (err) {
    SpreadsheetApp.getUi().alert(`ステータス更新に失敗しました: ${err.message}`);
    throw err;
  }
}

function refreshRequestReviewStatus_() {
  const sheet = getRequestReviewSheet_();
  ensureRequestReviewColumns_(sheet);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return;
  }

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  const requestIdCol = idx.request_id;
  if (!requestIdCol) {
    throw new Error('requests_review header missing: request_id');
  }

  const rows = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  const requestIds = rows
    .map((r) => String(r[requestIdCol - 1] || '').trim())
    .filter((v) => v);

  if (!requestIds.length) {
    return;
  }
  refreshRequestReviewStatusForRequestIds_(requestIds);
}

function refreshRequestReviewStatusForRequestIds_(requestIds) {
  const uniqueIds = Array.from(new Set((requestIds || []).map((v) => String(v).trim()).filter((v) => v)));
  if (!uniqueIds.length) return;

  const props = getProps_();
  const dataMap = queryLatestRequestStatusMap_(props, uniqueIds);
  const sheet = getRequestReviewSheet_();
  ensureRequestReviewColumns_(sheet);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  const rows = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  const nowStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');

  const outExec = [];
  const outReflect = [];
  const outChecked = [];
  for (let i = 0; i < rows.length; i += 1) {
    const reqId = String(rows[i][idx.request_id - 1] || '').trim();
    const info = dataMap[reqId];
    if (!info) {
      outExec.push(['未実行']);
      outReflect.push(['未確認']);
      outChecked.push([nowStr]);
      continue;
    }
    outExec.push([info.execution_result]);
    outReflect.push([info.final_reflection]);
    outChecked.push([nowStr]);
  }

  sheet.getRange(2, idx[COL_EXEC_RESULT], outExec.length, 1).setValues(outExec);
  sheet.getRange(2, idx[COL_FINAL_REFLECT], outReflect.length, 1).setValues(outReflect);
  sheet.getRange(2, idx[COL_LAST_CHECKED], outChecked.length, 1).setValues(outChecked);
}

function getRequestReviewSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(REQUEST_SHEET_NAME);
  if (!sheet) {
    throw new Error(`sheet not found: ${REQUEST_SHEET_NAME}`);
  }
  return sheet;
}

function ensureRequestReviewColumns_(sheet) {
  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const missing = [COL_EXEC_RESULT, COL_FINAL_REFLECT, COL_LAST_CHECKED].filter((name) => !header.includes(name));
  missing.forEach((name) => {
    sheet.getRange(1, sheet.getLastColumn() + 1).setValue(name);
  });
}

function queryLatestRequestStatusMap_(props, requestIds) {
  const sql = `
    WITH req AS (
      SELECT
        request_id,
        request_type,
        principal_email,
        resource_name,
        role
      FROM `${props.projectId}.${props.datasetId}.iam_access_requests`
      WHERE request_id IN UNNEST(@request_ids)
    ),
    latest_exec AS (
      SELECT
        request_id,
        ARRAY_AGG(STRUCT(result, executed_at) ORDER BY executed_at DESC LIMIT 1)[OFFSET(0)] AS ex
      FROM `${props.projectId}.${props.datasetId}.iam_access_change_log`
      WHERE request_id IN UNNEST(@request_ids)
      GROUP BY request_id
    ),
    actual AS (
      SELECT principal_email, resource_name, role
      FROM `${props.projectId}.${props.datasetId}.iam_policy_permissions`
    )
    SELECT
      req.request_id AS request_id,
      COALESCE(latest_exec.ex.result, '未実行') AS execution_result,
      CASE
        WHEN latest_exec.ex.result IS NULL THEN '未確認'
        WHEN req.request_type = 'REVOKE' AND actual.principal_email IS NULL THEN '反映済み'
        WHEN req.request_type = 'REVOKE' AND actual.principal_email IS NOT NULL THEN '未反映'
        WHEN req.request_type != 'REVOKE' AND actual.principal_email IS NOT NULL THEN '反映済み'
        WHEN req.request_type != 'REVOKE' AND actual.principal_email IS NULL THEN '未反映'
        ELSE '未確認'
      END AS final_reflection
    FROM req
    LEFT JOIN latest_exec USING (request_id)
    LEFT JOIN actual
      USING (principal_email, resource_name, role)
  `;

  const rows = runSelectQuery_(props, sql, [arrayParam_('request_ids', 'STRING', requestIds)]);
  const map = {};
  rows.forEach((r) => {
    map[String(r.request_id)] = {
      execution_result: String(r.execution_result || '未実行'),
      final_reflection: String(r.final_reflection || '未確認')
    };
  });
  return map;
}

function runSelectQuery_(props, sql, queryParameters) {
  const req = {
    query: sql,
    useLegacySql: false,
    parameterMode: 'NAMED',
    queryParameters,
    location: props.location
  };

  let result = BigQuery.Jobs.query(req, props.projectId);
  let jobId = result.jobReference && result.jobReference.jobId;
  while (!result.jobComplete && jobId) {
    Utilities.sleep(500);
    result = BigQuery.Jobs.getQueryResults(props.projectId, jobId, { location: props.location });
  }
  if (result.status && result.status.errorResult) {
    throw new Error(`BigQuery select failed: ${JSON.stringify(result.status.errorResult)}`);
  }

  const fields = ((result.schema || {}).fields || []).map((f) => f.name);
  const rows = result.rows || [];
  return rows.map((row) => {
    const obj = {};
    (row.f || []).forEach((cell, i) => {
      obj[fields[i]] = cell.v;
    });
    return obj;
  });
}

function arrayParam_(name, elemType, values) {
  return {
    name,
    parameterType: {
      type: 'ARRAY',
      arrayType: { type: elemType }
    },
    parameterValue: {
      arrayValues: values.map((v) => ({ value: String(v) }))
    }
  };
}

function indexMap_(headerRow) {
  const map = {};
  headerRow.forEach((name, i) => {
    const key = String(name || '').trim();
    if (key) {
      map[key] = i + 1;
    }
  });
  return map;
}
