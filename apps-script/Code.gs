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
 *    - GAS_INVOKER_SA_EMAIL
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
const FIELD_PROJECT = '対象プロジェクト';
const FIELD_ROLE = '付与・変更ロール';
const FIELD_REASON = '申請理由・利用目的';
const FIELD_REASON_ALT = '利用目的';
const FIELD_APPROVER = '承認者メール（または承認グループ）';
const COL_AI_SUGGEST = 'AI推奨（最小権限）';
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
    .addItem('未反映の承認済リクエストを再実行', 'menuRetryFailedExecutions_')
    .addSeparator()
    .addItem('不整合アラート(インシデント)の確認', 'menuPullReconciliationIssues_')
    .addToUi();
}


/**
 * Webアプリ(ポータル)からの申請を受け付けるエントリーポイント
 */
function submitAccessRequest(formData) {
  const props = getProps_();
  
  // サーバーサイド・バリデーション (セキュリティ強化)
  const role = String(formData.role || '').trim();
  if (role && !role.startsWith('roles/')) {
    throw new Error('セキュリティ違反: 「roles/」から始まる正式なロール名を指定してください。');
  }

  const rawRequestType = formData.requestType;
  const isEmergency = rawRequestType === '緊急付与' || rawRequestType.indexOf('緊急') !== -1 || rawRequestType.toUpperCase().indexOf('EMERGENCY') !== -1;
  const reason = (isEmergency ? '[緊急] ' : '') + String(formData.reason || '').trim();

  let expiresAt = null;
  const expiresRaw = formData.expiresAt;
  if (expiresRaw && expiresRaw !== '恒久' && expiresRaw.toUpperCase().indexOf('PERMANENT') === -1) {
    const d = new Date(expiresRaw);
    if (!isNaN(d.getTime())) {
      d.setHours(23, 59, 59, 999);
      expiresAt = d.toISOString();
    }
  }

  const requesterEmail = String(formData.requester || getActorEmail_()).trim();

  const request = {
    request_id: Utilities.getUuid(),
    request_type: normalizeRequestType_(rawRequestType),
    principal_email: String(formData.principal).trim(),
    resource_name: normalizeResourceName_(String(formData.resource)),
    role: role,
    reason: reason,
    expires_at: expiresAt,
    requester_email: requesterEmail,
    approver_email: String(formData.approver).trim(),
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
    acted_by: requesterEmail,
    actor_source: 'WEB_APP',
    details_json: JSON.stringify({ source: 'web_app' })
  });

  const aiSuggestion = formData.aiSuggestion || '';
  appendReviewSheet_(request, aiSuggestion);

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
    updateSheetStatus_(request.request_id, '承認済');
    refreshRequestReviewStatusForRequestIds_([request.request_id]);
  }

  return { success: true, request_id: request.request_id };
}

function handleEdit(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== REQUEST_SHEET_NAME) return;

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const statusCol = header.indexOf('status') + 1;
  const reqIdCol = header.indexOf('request_id');
  if (reqIdCol < 0 || statusCol <= 0) return;

  if (range.getColumn() > statusCol || range.getColumn() + range.getNumColumns() - 1 < statusCol) return;

  const props = getProps_();
  const startRow = range.getRow();
  const numRows = range.getNumRows();
  const rowData = sheet.getRange(startRow, 1, numRows, sheet.getLastColumn()).getValues();
  const idx = indexMap_(header);

  // 1. スパム通知を防ぐため、変更対象のIDの現在のステータスをBigQueryから取得
  const reqIdsToCheck = [];
  for (let i = 0; i < numRows; i++) {
    if (startRow + i === 1) continue;
    const row = rowData[i];
    const requestId = String(row[reqIdCol - 1] || '').trim();
    if (requestId) reqIdsToCheck.push(requestId);
  }

  let oldStatusMap = {};
  if (reqIdsToCheck.length > 0) {
    oldStatusMap = getRequestStatusesFromBQ_(props, reqIdsToCheck);
  }

  const updates = [];
  const requestIdsToExecute = [];
  const emailsToSend = [];

  for (let i = 0; i < numRows; i++) {
    if (startRow + i === 1) continue; // ヘッダーはスキップ
    const row = rowData[i];
    const requestId = String(row[reqIdCol] || '').trim();
    const newStatusRaw = String(row[statusCol - 1] || '').trim();

    if (requestId && newStatusRaw) {
      const normalizedStatus = normalizeStatus_(newStatusRaw);
      const oldStatus = oldStatusMap[requestId] || STATUS_PENDING;

      if (normalizedStatus !== oldStatus) {
        updates.push({ request_id: requestId, status: normalizedStatus });

        if (normalizedStatus === STATUS_APPROVED) {
          requestIdsToExecute.push(requestId);
        }

        if (normalizedStatus === STATUS_APPROVED || normalizedStatus === 'REJECTED') {
           const requesterEmail = String(row[idx.requester_email - 1] || '');
           if (requesterEmail) {
             const prefillData = {
               [FIELD_REQUEST_TYPE]: String(row[idx.request_type - 1] || ''),
               [FIELD_PRINCIPAL]: String(row[idx.principal_email - 1] || ''),
               [FIELD_RESOURCE]: String(row[idx.resource_name - 1] || ''),
               [FIELD_ROLE]: String(row[idx.role - 1] || ''),
               [FIELD_REASON]: String(row[idx.reason - 1] || ''),
               [FIELD_APPROVER]: String(row[idx.approver_email - 1] || '')
             };
             emailsToSend.push({ type: normalizedStatus, prefillData: prefillData, requester: requesterEmail });
           }
        }
      }
    }
  }

  if (updates.length === 0) return;

  const token = getOidcToken_(props);
  const baseUrl = props.cloudRunUrl.replace(/\/execute\/?$/, '');
  const actorEmail = getActorEmail_();

  // 1. スナップショットなどの複雑な処理はすべてバックエンドに任せ、IDとステータスだけを送る
  try {
    const bulkPayload = { updates: updates, actor_email: actorEmail };
    const res = UrlFetchApp.fetch(`${baseUrl}/api/requests/bulk-status`, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(bulkPayload),
      headers: { Authorization: `Bearer ${token}` },
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 400) {
      console.error("Bulk update failed: " + res.getContentText());
      return;
    }
  } catch (e) {
    console.error("Bulk API error: " + e);
    return;
  }

  // 2. 更新が成功したら、承認済みのものだけ並列で /execute を叩く
  if (requestIdsToExecute.length > 0) {
    const executeRequests = requestIdsToExecute.map(id => ({
      url: `${baseUrl}/execute`,
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ request_id: id }),
      headers: { Authorization: `Bearer ${token}` },
      muteHttpExceptions: true
    }));
    try {
      const responses = UrlFetchApp.fetchAll(executeRequests);
      responses.forEach((res, i) => {
        if (res.getResponseCode() >= 300) {
          console.error(`Execute API failed for request ${requestIdsToExecute[i]} (${res.getResponseCode()}): ${res.getContentText()}`);
        }
      });
    } catch (e) {
      console.error("Execute API error (Network): " + e);
    }
  }

  const allIds = updates.map(u => u.request_id);
  refreshRequestReviewStatusForRequestIds_(allIds);

  // 3. API実行などがすべて終わった後に通知メールを送信
  if (emailsToSend.length > 0) {
    sendNotificationEmails_(emailsToSend);
  }
}

function callCloudRunApi_(props, path, method, payloadObj) {
  const token = getOidcToken_(props);
  const url = props.cloudRunUrl.replace(/\/execute\/?$/, '') + path;
  const options = {
    method: method,
    contentType: 'application/json',
    payload: JSON.stringify(payloadObj),
    headers: { Authorization: `Bearer ${token}` },
    muteHttpExceptions: true
  };
  const maxRetries = 3;
  for (let i = 0; i < maxRetries; i++) {
    try {
      const resp = UrlFetchApp.fetch(url, options);
      const code = resp.getResponseCode();
      if (code >= 300) {
        throw new Error(`Cloud Run API failed (${code}): ${resp.getContentText()}`);
      }
      return;
    } catch (err) {
      if (i === maxRetries - 1) throw err;
      Utilities.sleep(1000 * (i + 1));
    }
  }
}

function insertRequestToBigQuery_(props, request) {
  const payload = {
    request_id: request.request_id,
    request_type: request.request_type,
    principal_email: request.principal_email,
    resource_name: request.resource_name,
    role: request.role,
    reason: request.reason,
    expires_at: request.expires_at || null,
    requester_email: request.requester_email,
    approver_email: request.approver_email,
    status: request.status,
    requested_at: request.requested_at,
    ticket_ref: request.ticket_ref,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  };
  callCloudRunApi_(props, '/api/requests', 'post', payload);
}

function updateStatusInBigQuery_(props, requestId, normalizedStatus) {
  const payload = { status: normalizedStatus };
  callCloudRunApi_(props, `/api/requests/${requestId}/status`, 'put', payload);
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
    FROM \`${props.projectId}.${props.datasetId}.iam_access_requests\`
    WHERE request_id = @request_id
    LIMIT 1
  `;
  const rows = runSelectQuery_(props, sql, [param_('request_id', 'STRING', String(requestId))]);
  return rows.length ? rows[0] : null;
}

function insertRequestHistoryEvent_(props, event) {
  const payload = {
    history_id: Utilities.getUuid(),
    request_id: String(event.request_id || ''),
    event_type: String(event.event_type || ''),
    old_status: String(event.old_status || ''),
    new_status: String(event.new_status || ''),
    reason_snapshot: String(event.reason_snapshot || ''),
    request_type: String(event.request_type || ''),
    principal_email: String(event.principal_email || ''),
    resource_name: String(event.resource_name || ''),
    role: String(event.role || ''),
    requester_email: String(event.requester_email || ''),
    approver_email: String(event.approver_email || ''),
    acted_by: String(event.acted_by || 'unknown'),
    actor_source: String(event.actor_source || 'UNKNOWN'),
    event_at: new Date().toISOString(),
    details: event.details_json ? JSON.parse(event.details_json) : {}
  };
  callCloudRunApi_(props, '/api/history', 'post', payload);
}

function getOidcToken_(props) {
  if (!props.gasInvokerEmail) throw new Error("Missing GAS_INVOKER_SA_EMAIL property");
  const url = `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${props.gasInvokerEmail}:generateIdToken`;
  const payload = {
    audience: props.cloudRunUrl.replace(/\/execute\/?$/, ''),
    includeEmail: true
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    headers: {
      Authorization: `Bearer ${ScriptApp.getOAuthToken()}`
    },
    muteHttpExceptions: true
  };
  const res = UrlFetchApp.fetch(url, options);
  const code = res.getResponseCode();
  const text = res.getContentText();
  if (code >= 300) {
    throw new Error(`Failed to get OIDC token from IAM Credentials API (${code}): ${text}`);
  }
  return JSON.parse(text).token;
}

function callCloudRunExecute_(props, requestId) {
  callCloudRunApi_(props, '/execute', 'post', { request_id: String(requestId) });
}

function appendReviewSheet_(request, aiSuggestion) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(REQUEST_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(REQUEST_SHEET_NAME);
    sheet.appendRow([
      'request_id', 'request_type', 'principal_email', 'resource_name', 'role',
      'reason', 'expires_at', 'requester_email', 'approver_email', 'status', 'requested_at', 'ticket_ref', COL_AI_SUGGEST
    ]);
  }

  ensureRequestReviewColumns_(sheet);

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  let rowData = new Array(header.length).fill('');
  
  if (idx.request_id) rowData[idx.request_id - 1] = request.request_id;
  if (idx.request_type) rowData[idx.request_type - 1] = request.request_type;
  if (idx.principal_email) rowData[idx.principal_email - 1] = request.principal_email;
  if (idx.resource_name) rowData[idx.resource_name - 1] = request.resource_name;
  if (idx.role) rowData[idx.role - 1] = request.role;
  if (idx.reason) rowData[idx.reason - 1] = request.reason;
  if (idx.expires_at) rowData[idx.expires_at - 1] = request.expires_at ? new Date(request.expires_at).toLocaleString() : '恒久';
  if (idx.requester_email) rowData[idx.requester_email - 1] = request.requester_email;
  if (idx.approver_email) rowData[idx.approver_email - 1] = request.approver_email;
  if (idx.status) {
    // ドロップダウンでエラー（赤い警告）にならないよう、初期ステータスを日本語にします
    rowData[idx.status - 1] = request.status === STATUS_PENDING ? '申請中' : request.status;
  }
  if (idx.requested_at) rowData[idx.requested_at - 1] = request.requested_at;
  if (idx.ticket_ref) rowData[idx.ticket_ref - 1] = request.ticket_ref;
  if (idx[COL_AI_SUGGEST]) rowData[idx[COL_AI_SUGGEST] - 1] = aiSuggestion || '（事前AI推論なし・ロール存在確認済）';
  if (idx[COL_EXEC_RESULT]) rowData[idx[COL_EXEC_RESULT] - 1] = '未実行';
  if (idx[COL_FINAL_REFLECT]) rowData[idx[COL_FINAL_REFLECT] - 1] = '未確認';
  if (idx[COL_LAST_CHECKED]) rowData[idx[COL_LAST_CHECKED] - 1] = '-';

  sheet.appendRow(rowData);

  // statusカラム全体（2行目以降）にドロップダウンリスト（データの入力規則）を自動設定
  if (idx.status) {
    const lastRow = sheet.getLastRow();
    if (lastRow >= 2) {
      const rule = SpreadsheetApp.newDataValidation()
        .requireValueInList(['申請中', '承認済', '却下', '取消'], true)
        .setAllowInvalid(false) // リスト以外の無効な入力をブロック
        .build();
      sheet.getRange(2, idx.status, lastRow - 1, 1).setDataValidation(rule);
    }
  }
}

function updateSheetStatus_(requestId, newStatusJa) {
  const sheet = getRequestReviewSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  
  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idCol = header.indexOf('request_id') + 1;
  const statusCol = header.indexOf('status') + 1;
  if (!idCol || !statusCol) return;
  
  const ids = sheet.getRange(2, idCol, lastRow - 1, 1).getValues();
  for (let i = 0; i < ids.length; i++) {
    if (String(ids[i][0]).trim() === String(requestId).trim()) {
      sheet.getRange(i + 2, statusCol).setValue(newStatusJa);
      break;
    }
  }
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
    gasInvokerEmail: p.getProperty('GAS_INVOKER_SA_EMAIL')
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

function getStatusMapping_(props) {
  const cache = CacheService.getScriptCache();
  const cached = cache.get('status_mapping');
  if (cached) return JSON.parse(cached);

  let mapping = { '承認済': 'APPROVED', '申請中': 'PENDING', '却下': 'REJECTED', '取消': 'CANCELLED' }; // Fallback
  try {
    const token = getOidcToken_(props);
    const url = props.cloudRunUrl.replace(/\/execute\/?$/, '') + '/api/statuses';
    const options = {
      method: 'get',
      headers: { Authorization: `Bearer ${token}` },
      muteHttpExceptions: true
    };
    const resp = UrlFetchApp.fetch(url, options);
    if (resp.getResponseCode() === 200) {
       const data = JSON.parse(resp.getContentText());
       mapping = data.mapping;
       cache.put('status_mapping', JSON.stringify(mapping), 3600); // 1時間キャッシュ
    }
  } catch(e) {
    console.warn('Failed to fetch status mapping from API: ' + e);
  }
  return mapping;
}

function normalizeStatus_(raw) {
  const v = String(raw || '').trim();
  if (!v) return STATUS_PENDING;
  try {
    const props = getProps_();
    const map = getStatusMapping_(props);
    return map[v] || v;
  } catch(e) {
    return v;
  }
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
  const props = getProps_();
  
  // 1. BigQueryから最新の帳票データを直接取得
  const sql = "SELECT * FROM `" + props.projectId + "." + props.datasetId + ".v_sheet_iam_permission_history`";
  const req = { query: sql, useLegacySql: false, location: props.location };
  
  let bqResult = BigQuery.Jobs.query(req, props.projectId);
  let jobId = bqResult.jobReference && bqResult.jobReference.jobId;
  
  while (!bqResult.jobComplete && jobId) {
    Utilities.sleep(500);
    bqResult = BigQuery.Jobs.getQueryResults(props.projectId, jobId, { location: props.location });
  }
  if (bqResult.status && bqResult.status.errorResult) {
    throw new Error('BigQuery query failed: ' + JSON.stringify(bqResult.status.errorResult));
  }

  const headers = ((bqResult.schema || {}).fields || []).map(f => f.name);
  const rows = bqResult.rows || [];
  if (rows.length === 0) {
     throw new Error('履歴データがありません。');
  }
  
  // データのクレンジング処理
  const idx = indexMap_(headers);
  const roleColIdx = idx['IAMロール'] ? idx['IAMロール'] - 1 : -1;
  const resourceColIdx = idx['リソースID'] ? idx['リソースID'] - 1 : -1;

  const values = [headers];
  rows.forEach(row => {
    let rowData = (row.f || []).map(cell => cell.v);
    
    // 1) ロール名から 'roles/' を除去して列幅を節約
    if (roleColIdx >= 0 && rowData[roleColIdx]) {
      rowData[roleColIdx] = String(rowData[roleColIdx]).replace(/^roles\//, '');
    }
    // 2) リソースIDがNULL/空白の場合は明示的に文字を入れる
    if (resourceColIdx >= 0 && !rowData[resourceColIdx]) {
      rowData[resourceColIdx] = props.projectId;
    }
    values.push(rowData);
  });

  const TMP_SHEET_NAME = '_tmp_matrix_source';
  let tmpSheet = ss.getSheetByName(TMP_SHEET_NAME);
  if (!tmpSheet) {
    tmpSheet = ss.insertSheet(TMP_SHEET_NAME);
    tmpSheet.hideSheet();
  } else {
    tmpSheet.clear();
  }

  tmpSheet.getRange(1, 1, values.length, values[0].length).setValues(values);

  let matrix = ss.getSheetByName(MATRIX_SHEET_NAME);
  if (!matrix) {
    matrix = ss.insertSheet(MATRIX_SHEET_NAME);
  } else {
    matrix.clear();
    matrix.getBandings().forEach(b => b.remove());
    matrix.clearFormats();
  }
  
  matrix.getRange(1, 1).setValue('IAM権限設定履歴ベースのピボット（BigQuery直接取得・超安定版）');
  
  const sourceRange = tmpSheet.getDataRange();
  const pivot = matrix.getRange(3, 1).createPivotTable(sourceRange);

  pivot.addRowGroup(idx['プリンシパル']).showTotals(false);
  pivot.addRowGroup(idx['リソースID']).showTotals(false);
  pivot.addColumnGroup(idx['IAMロール']).showTotals(false);
  
  // ★ステータス列が空だとカウント0になるため、必ず値がある「プリンシパル」列をカウント対象に変更
  pivot.addPivotValue(idx['プリンシパル'], SpreadsheetApp.PivotTableSummarizeFunction.COUNTA);

  SpreadsheetApp.flush();
  
  const maxCol = matrix.getLastColumn();
  const lastPivotRow = matrix.getLastRow();

  if (maxCol > 2) {
    matrix.getRange(1, 1, lastPivotRow, maxCol).setNumberFormat('"○";"";"";@');
    
    // ヘッダーの装飾と折り返し設定
    const headerRange = matrix.getRange(3, 3, 2, maxCol - 2);
    headerRange.setBackground('#4b746c').setFontColor('white').setFontStyle('italic');
    // 3行目は横書きのまま、4行目（ロール名）のみ縦書き（90度回転）にする
    matrix.getRange(4, 3, 1, maxCol - 2).setTextRotation(90);
    
    matrix.getRange(3, 1, 2, 2).setBackground('#f3f3f3').setFontColor('black').setFontStyle('italic');
    matrix.getRange(1, 1, lastPivotRow, maxCol).setHorizontalAlignment('center').setVerticalAlignment('middle');
    matrix.getRange(1, 1, lastPivotRow, 2).setHorizontalAlignment('left');
    matrix.getRange(3, 3).setHorizontalAlignment('left');
    
    // 列幅の調整
    matrix.setColumnWidth(1, 400);
    matrix.setColumnWidth(2, 160);
    for (let c = 3; c <= maxCol; c++) {
      matrix.setColumnWidth(c, 35);
    }

    if (lastPivotRow >= 5) {
      const dataRangeBanding = matrix.getRange(5, 1, lastPivotRow - 4, maxCol);
      dataRangeBanding.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, false, false);
    }
  }
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
function menuPullReconciliationIssues_() {
  try {
    const count = pullReconciliationIssuesFromBQ_();
    if (count > 0) {
      SpreadsheetApp.getActiveSpreadsheet().toast(`新たに ${count} 件の不整合アラートを検知しました。`, 'アラート', 5);
    } else {
      SpreadsheetApp.getActiveSpreadsheet().toast('現在OPENな不整合（インシデント）はありません。', 'アラート', 5);
    }
  } catch (err) {
    SpreadsheetApp.getUi().alert(`アラートの取得に失敗しました: ${err.message}`);
    throw err;
  }
}

function pullReconciliationIssuesFromBQ_() {
  const SHEET_NAME = '不整合アラート';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  
  // アラートの現状を洗い替えて表示する
  sheet.clear();
  sheet.appendRow(['検知日時', '深刻度', 'アラート種別', 'プリンシパル', 'リソース', 'ロール', '関連申請ID', 'ステータス']);
  sheet.getRange(1, 1, 1, 8).setFontWeight('bold').setBackground('#f4c7c3'); // ヘッダーを赤色強調
  
  const props = getProps_();
  const sql = `
    SELECT 
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', detected_at, '${Session.getScriptTimeZone()}') as detected_at,
      severity, issue_type, principal_email, resource_name, role, request_id, status
    FROM \`${props.projectId}.${props.datasetId}.iam_reconciliation_issues\`
    WHERE status = 'OPEN'
    ORDER BY detected_at DESC
    LIMIT 1000
  `;
  
  const rows = runSelectQuery_(props, sql, []);
  if (!rows.length) return 0;
  
  const out = rows.map(r => [
    r.detected_at, r.severity, r.issue_type, r.principal_email, r.resource_name, r.role, r.request_id || '（システム管理外）', r.status
  ]);
  
  sheet.getRange(2, 1, out.length, out[0].length).setValues(out);
  return out.length;
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
  const missing = ['expires_at', COL_AI_SUGGEST, COL_EXEC_RESULT, COL_FINAL_REFLECT, COL_LAST_CHECKED].filter((name) => !header.includes(name));
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
      FROM \`${props.projectId}.${props.datasetId}.iam_access_requests\`
      WHERE request_id IN UNNEST(@request_ids)
    ),
    latest_exec AS (
      SELECT
        request_id,
        ARRAY_AGG(STRUCT(result, executed_at) ORDER BY executed_at DESC LIMIT 1)[OFFSET(0)] AS ex
      FROM \`${props.projectId}.${props.datasetId}.iam_access_change_log\`
      WHERE request_id IN UNNEST(@request_ids)
      GROUP BY request_id
    ),
    actual AS (
      SELECT principal_email, resource_name, role
      FROM \`${props.projectId}.${props.datasetId}.iam_policy_permissions\`
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

function normalizeResourceName_(raw) {
  let v = String(raw || '').trim();
  if (!v) return v;
  
  // すでに正しいプレフィックスが付いている場合はそのまま
  if (v.startsWith('projects/') || v.startsWith('folders/') || v.startsWith('organizations/')) {
    return v;
  }
  
  // プレフィックスがない場合は、最も一般的な「プロジェクトID」と推測して補完する
  return 'projects/' + v;
}

function getRequestStatusesFromBQ_(props, requestIds) {
  if (!requestIds || requestIds.length === 0) return {};
  const sql = `SELECT request_id, status FROM \`${props.projectId}.${props.datasetId}.iam_access_requests\` WHERE request_id IN UNNEST(@request_ids)`;
  try {
    const rows = runSelectQuery_(props, sql, [arrayParam_('request_ids', 'STRING', requestIds)]);
    const map = {};
    rows.forEach(r => { map[String(r.request_id)] = String(r.status); });
    return map;
  } catch(e) {
    console.error('getRequestStatusesFromBQ_ error: ' + e);
    return {};
  }
}

function sendNotificationEmails_(emailsToSend) {
  emailsToSend.forEach(item => {
    const type = item.type;
    const prefillData = item.prefillData;
    const requester = item.requester;
    if (!requester) return;
    
    const resource = prefillData[FIELD_RESOURCE] || prefillData[FIELD_PROJECT] || '';
    const role = prefillData[FIELD_ROLE] || '';
    const reason = prefillData[FIELD_REASON] || prefillData[FIELD_REASON_ALT] || '';
    
    if (type === STATUS_APPROVED) {
      const subject = `【Cloud Access Manager】IAM権限申請が承認されました`;
      const body = `以下のIAM権限申請が承認され、自動付与処理が開始されました。\n\n`
        + `対象リソース: ${resource}\n`
        + `ロール: ${role}\n`
        + `申請理由: ${reason}\n\n`
        + `数分以内にGoogle Cloud環境へ反映されます。`;
      try {
        MailApp.sendEmail(requester, subject, body);
      } catch (e) {
        console.error("MailApp error (APPROVED): " + e);
      }
    } else if (type === 'REJECTED') {
      const subject = `【Cloud Access Manager】IAM権限申請が却下されました`;
      const prefilledUrl = generatePrefilledUrl_(prefillData) || '(フォームのURLを取得できませんでした)';
      
      const body = `以下のIAM権限申請が却下されました。\n\n`
        + `対象リソース: ${resource}\n`
        + `ロール: ${role}\n`
        + `申請理由: ${reason}\n\n`
        + `内容を修正して再申請する場合は、以下の事前入力リンクから申請してください:\n`
        + `${prefilledUrl}`;
      try {
        MailApp.sendEmail(requester, subject, body);
      } catch (e) {
        console.error("MailApp error (REJECTED): " + e);
      }
    }
  });
}

function generatePrefilledUrl_(prefillData) {
  try {
    const webAppUrl = ScriptApp.getService().getUrl();
    if (!webAppUrl) return '(SaaSポータルのWebアプリURLを取得できませんでした)';
    
    const params = [];
    for (const key in prefillData) {
      if (prefillData[key]) {
        params.push(encodeURIComponent(key) + '=' + encodeURIComponent(prefillData[key]));
      }
    }
    return webAppUrl + (params.length > 0 ? '?' + params.join('&') : '');
  } catch (e) {
    console.error("generatePrefilledUrl_ error: " + e);
    return '(SaaSポータルのWebアプリURLを取得できませんでした)';
  }
}

function menuRetryFailedExecutions_() {
  const ui = SpreadsheetApp.getUi();
  const sheet = getRequestReviewSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    ui.alert('再実行するデータがありません。');
    return;
  }

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  const reqIdCol = idx.request_id;
  const statusCol = idx.status;
  const execResultCol = idx[COL_EXEC_RESULT];

  if (!reqIdCol || !statusCol || !execResultCol) {
    ui.alert('必要なカラムが見つかりません。先に「申請反映ステータス更新」メニューを実行してください。');
    return;
  }

  const rows = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  const targetIds = [];

  // 「承認済」かつ「実行結果がSUCCESS/SKIPPED以外」のものを探す
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const requestId = String(row[reqIdCol - 1] || '').trim();
    const statusRaw = String(row[statusCol - 1] || '').trim();
    const execResult = String(row[execResultCol - 1] || '').trim();

    const normalizedStatus = normalizeStatus_(statusRaw);
    if (normalizedStatus === STATUS_APPROVED && execResult !== 'SUCCESS' && execResult !== 'SKIPPED') {
      if (requestId) {
        targetIds.push(requestId);
      }
    }
  }

  if (targetIds.length === 0) {
    ui.alert('再実行が必要な承認済リクエスト（未実行・失敗）は見つかりませんでした。');
    return;
  }

  const response = ui.alert('再実行の確認', `${targetIds.length}件の未反映リクエストを再実行しますか？`, ui.ButtonSet.YES_NO);
  if (response !== ui.Button.YES) return;

  const props = getProps_();
  const token = getOidcToken_(props);
  const baseUrl = props.cloudRunUrl.replace(/\/execute\/?$/, '');

  // 対象となるリクエストの実行API呼び出しを並列で準備
  const executeRequests = targetIds.map(id => ({
    url: `${baseUrl}/execute`,
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ request_id: id }),
    headers: { Authorization: `Bearer ${token}` },
    muteHttpExceptions: true
  }));

  try {
    const responses = UrlFetchApp.fetchAll(executeRequests);
    let successCount = 0;
    responses.forEach((res, i) => {
      if (res.getResponseCode() < 300) {
        successCount++;
      } else {
        console.error(`Execute API failed for request ${targetIds[i]} (${res.getResponseCode()}): ${res.getContentText()}`);
      }
    });

    // 実行後、ステータスを自動更新する
    refreshRequestReviewStatusForRequestIds_(targetIds);
    ui.alert('再実行完了', `${targetIds.length}件中 ${successCount}件の再実行リクエストを送信し、ステータスを更新しました。`, ui.ButtonSet.OK);

  } catch (e) {
    console.error("Retry execution error: " + e);
    ui.alert(`再実行中にエラーが発生しました: ${e.message}`);
  }
}


// =========================================================================
// BigQueryから直接データを取得し、指定シートに展開する汎用関数
// =========================================================================
function refreshSheetFromBigQuery_(sheetName, viewName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const props = getProps_();
  
  // BigQueryから直接取得
  const sql = "SELECT * FROM `" + props.projectId + "." + props.datasetId + "." + viewName + "`";
  const req = { query: sql, useLegacySql: false, location: props.location };
  
  let bqResult = BigQuery.Jobs.query(req, props.projectId);
  let jobId = bqResult.jobReference && bqResult.jobReference.jobId;
  
  while (!bqResult.jobComplete && jobId) {
    Utilities.sleep(500);
    bqResult = BigQuery.Jobs.getQueryResults(props.projectId, jobId, { location: props.location });
  }
  if (bqResult.status && bqResult.status.errorResult) {
    throw new Error(`BigQuery query failed for ${viewName}: ` + JSON.stringify(bqResult.status.errorResult));
  }

  // シートの準備
  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
  } else {
    sheet.clear();
    sheet.getBandings().forEach(b => b.remove());
  }

  // データが0件でも、スキーマ情報からヘッダー（カラム名）は取得する
  const headers = ((bqResult.schema || {}).fields || []).map(f => f.name);
  const values = [headers];

  const rows = bqResult.rows || [];
  if (rows.length === 0) {
    const emptyRow = new Array(headers.length).fill('');
    emptyRow[0] = 'データがありません';
    values.push(emptyRow);
  } else {
    rows.forEach(row => {
      values.push((row.f || []).map(cell => cell.v));
    });
  }

  // 一括書き込みと簡易フォーマット
  sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
  sheet.getRange(1, 1, 1, headers.length).setBackground('#f3f3f3').setFontWeight('bold');
  sheet.getRange(1, 1, 1, headers.length).setBackground('#4b746c').setFontColor('white').setFontWeight('normal');
  
  // フィルターが存在しなければ追加
  if (!sheet.getFilter()) {
    sheet.getDataRange().createFilter();
  }
  SpreadsheetApp.flush();
}

// -------------------------------------------------------------------------
// 各シートの更新用関数（カスタムメニュー等から呼び出し可能）
// -------------------------------------------------------------------------
function refreshGroupsSheet() {
  // ※ビュー名は実際のBigQuery環境に合わせて適宜修正してください
  refreshSheetFromBigQuery_('グループ', 'v_sheet_group');
}

function refreshGroupMembersSheet() {
  refreshSheetFromBigQuery_('グループメンバー', 'v_sheet_group_members');
}

function refreshResourcesSheet() {
  refreshSheetFromBigQuery_('リソース', 'v_sheet_resource');
}

// 3つのマスターシートを一括更新する関数
function refreshAllMasterData() {
  refreshGroupsSheet();
  refreshGroupMembersSheet();
  refreshResourcesSheet();
  SpreadsheetApp.getUi().alert("✅ マスターデータ（グループ・メンバー・リソース）の最新化が完了しました。");
}
