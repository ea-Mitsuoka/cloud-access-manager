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
 * 認証: スクリプトプロパティは不要です。ScriptApp.getOAuthToken() を使用し、Vertex AI経由でセキュアに認証・実行されます。
 * 3) Create installable triggers:
 *    - refreshRequestReviewStatus_ (From spreadsheet, Time-driven)
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
    .addItem('📥 新規申請を取り込む', 'menuPullNewRequests_')
    .addItem('🔄 レビュー結果を一括送信', 'menuSubmitBulkReview_')
    .addItem('マトリクス更新', 'menuRefreshIamMatrixPivot_')
    .addItem('マスタ一括更新 (プリンシパル/グループ等)', 'refreshAllMasterData')
    .addItem('未反映の承認済リクエストを再実行', 'menuRetryFailedExecutions_')
    .addSeparator()
    .addItem('最新ステータス取得', 'menuRefreshRequestReviewStatus_')
    .addSeparator()
    .addItem('不整合アラート(インシデント)の確認', 'menuPullReconciliationIssues_')
    .addToUi();
}

function menuPullNewRequests_() {
  try {
    const count = pullNewRequestsFromBQ_();
    if (count > 0) {
      SpreadsheetApp.getActiveSpreadsheet().toast(`📥 新規の申請を ${count} 件取り込みました。`, '棚卸し', 5);
    } else {
      SpreadsheetApp.getActiveSpreadsheet().toast('新しい申請はありません。', '棚卸し', 3);
    }
  } catch(e) {
    SpreadsheetApp.getUi().alert(`申請の取り込みに失敗しました: ${e.message}`);
    throw e;
  }
}

function pullNewRequestsFromBQ_() {
  const sheet = getRequestReviewSheet_();
  ensureRequestReviewColumns_(sheet);
  const lastRow = sheet.getLastRow();
  const existingIds = new Set();
  
  if (lastRow >= 2) {
    const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    const idx = indexMap_(header);
    if (idx.request_id) {
      const ids = sheet.getRange(2, idx.request_id, lastRow - 1, 1).getValues();
      ids.forEach(r => { if(r[0]) existingIds.add(String(r[0]).trim()); });
    }
  }
  
  const props = getProps_();
  const tz = Session.getScriptTimeZone();
  const sql = `
    SELECT 
      r.request_group_id, r.request_id, r.request_type, r.principal_email, r.resource_name, r.role,
      r.reason, FORMAT_TIMESTAMP('%Y/%m/%d %H:%M:%S', r.expires_at, '${tz}') AS expires_at, 
      r.requester_email, r.approver_email, r.status, 
      FORMAT_TIMESTAMP('%Y/%m/%d %H:%M:%S', r.requested_at, '${tz}') AS requested_at, 
      r.ticket_ref,
      JSON_EXTRACT_SCALAR(h.details, '$.ai_suggestion') AS ai_suggestion
    FROM \`${props.projectId}.${props.datasetId}.iam_access_requests\` r
    LEFT JOIN \`${props.projectId}.${props.datasetId}.iam_access_request_history\` h
      ON r.request_id = h.request_id AND h.event_type = 'REQUESTED'
    WHERE r.status = 'PENDING'
    ORDER BY r.requested_at ASC
  `;
  
  const rows = runSelectQuery_(props, sql, []);
  let addedCount = 0;
  
  rows.forEach(req => {
    if (!existingIds.has(String(req.request_id))) {
      const formattedReq = Object.assign({}, req);
      let typeJa = '新規付与';
      if (req.request_type === 'REVOKE') typeJa = '削除';
      if (req.request_type === 'CHANGE') typeJa = '変更';
      formattedReq.request_type = typeJa;
      
      appendReviewSheet_(formattedReq, req.ai_suggestion);
      existingIds.add(String(req.request_id));
      addedCount++;
    }
  });
  return addedCount;
}

function handleEdit(e) {
  // Legacy no-op: ステータス編集時の自動API実行は廃止し、
  // メニュー「🔄 レビュー結果を一括送信」で明示実行する。
  return;
}

function menuSubmitBulkReview_() {
  const ui = SpreadsheetApp.getUi();
  const sheet = getRequestReviewSheet_();
  ensureRequestReviewColumns_(sheet);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    ui.alert('処理対象のレビュー行がありません。');
    return;
  }

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  if (!idx.request_id || !idx.status) {
    ui.alert('requests_review の必須カラム（request_id / status）が不足しています。');
    return;
  }

  const rows = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  const reviewRows = [];
  rows.forEach((row, i) => {
    const requestId = String(row[idx.request_id - 1] || '').trim();
    const statusRaw = String(row[idx.status - 1] || '').trim();
    if (!requestId || !statusRaw || statusRaw === '申請中') return;
    reviewRows.push({
      rowNumber: i + 2,
      request_id: requestId,
      status: normalizeStatus_(statusRaw),
      rowData: row
    });
  });

  if (reviewRows.length === 0) {
    ui.alert('「申請中」以外に変更された行がありません。');
    return;
  }

  let rejectReason = '';
  const hasRejected = reviewRows.some(item => item.status === 'REJECTED');
  if (hasRejected) {
    const prompt = ui.prompt(
      '却下理由の入力',
      '却下行が含まれています。監査のため却下理由を入力してください（全却下行に共通適用）。',
      ui.ButtonSet.OK_CANCEL
    );
    if (prompt.getSelectedButton() !== ui.Button.OK) {
      ui.alert('処理をキャンセルしました。');
      return;
    }
    rejectReason = String(prompt.getResponseText() || '').trim();
    if (!rejectReason) {
      ui.alert('却下理由は必須です。');
      return;
    }
  }

  const reviews = reviewRows.map(item => ({
    request_id: item.request_id,
    status: item.status,
    reject_reason: item.status === 'REJECTED' ? rejectReason : ''
  }));

  const confirm = ui.alert(
    '一括送信の確認',
    `${reviews.length}件のレビュー結果を一括送信しますか？`,
    ui.ButtonSet.YES_NO
  );
  if (confirm !== ui.Button.YES) return;

  const props = getProps_();
  const token = getOidcToken_(props);
  const baseUrl = props.cloudRunUrl.replace(/\/execute\/?$/, '');
  const actorEmail = getActorEmail_();

  let result;
  try {
    const res = UrlFetchApp.fetch(`${baseUrl}/api/v1/requests/bulk-review`, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        reviews: reviews,
        actor_email: actorEmail
      }),
      headers: { Authorization: `Bearer ${token}` },
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 400) {
      throw new Error(`Bulk review API failed (${res.getResponseCode()}): ${res.getContentText()}`);
    }
    result = JSON.parse(res.getContentText() || '{}');
  } catch (e) {
    ui.alert(`一括送信に失敗しました: ${e.message}`);
    throw e;
  }

  const succeeded = Array.isArray(result.succeeded) ? result.succeeded : [];
  const failed = Array.isArray(result.failed) ? result.failed : [];
  const successMap = {};
  succeeded.forEach(item => {
    const requestId = String(item.request_id || '').trim();
    if (requestId) successMap[requestId] = item;
  });
  const failedMap = {};
  failed.forEach(item => {
    const requestId = String(item.request_id || '').trim();
    if (requestId) failedMap[requestId] = item;
  });

  const failedIds = Object.keys(failedMap);
  if (failedIds.length > 0 && idx[COL_EXEC_RESULT]) {
    reviewRows.forEach(item => {
      const failure = failedMap[item.request_id];
      if (!failure) return;
      const msg = `${failure.error_code || 'ERROR'}: ${failure.error_message || 'failed'}`;
      sheet.getRange(item.rowNumber, idx[COL_EXEC_RESULT]).setValue(msg);
      if (idx[COL_FINAL_REFLECT]) {
        sheet.getRange(item.rowNumber, idx[COL_FINAL_REFLECT]).setValue('エラー');
      }
      if (idx[COL_LAST_CHECKED]) {
        sheet.getRange(item.rowNumber, idx[COL_LAST_CHECKED]).setValue(new Date().toLocaleString());
      }
    });
    // 失敗行の即時リフレッシュを削除（APIから返った詳細なエラーメッセージがBigQueryの「未実行」等で上書きされるのを防ぐため）
  }

  const historySheet = getProcessedHistorySheet_(header);
  const rowsToMove = reviewRows
    .filter(item => Boolean(successMap[item.request_id]))
    .map(item => item.rowNumber)
    .sort((a, b) => b - a);

 rowsToMove.forEach(rowNumber => {
    const rowData = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getValues()[0];
    
    // ★追加: 履歴に逃がす前に、成功したという「証」をデータに上書きする
    const reqId = String(rowData[idx.request_id - 1] || '').trim();
    const successData = successMap[reqId];
    if (successData) {
      if (idx[COL_EXEC_RESULT]) {
        // APIから返ってきた結果(SUCCESSやSKIPPED)をセット、なければSUCCESS
        rowData[idx[COL_EXEC_RESULT] - 1] = successData.execution_result || 'SUCCESS';
      }
      if (idx[COL_LAST_CHECKED]) {
        rowData[idx[COL_LAST_CHECKED] - 1] = new Date().toLocaleString();
      }
    }
    
    historySheet.appendRow(rowData);
    sheet.deleteRow(rowNumber);
  });

  const emailsToSend = [];
  succeeded.forEach(item => {
    const requestId = String(item.request_id || '').trim();
    const row = reviewRows.find(r => r.request_id === requestId);
    if (!row) return;
    const requesterEmail = idx.requester_email ? String(row.rowData[idx.requester_email - 1] || '') : '';
    const normalizedStatus = String(item.status || '');
    if (!requesterEmail || (normalizedStatus !== 'APPROVED' && normalizedStatus !== 'REJECTED')) return;
    emailsToSend.push({
      type: normalizedStatus,
      requester: requesterEmail,
      prefillData: {
        [FIELD_REQUEST_TYPE]: idx.request_type ? String(row.rowData[idx.request_type - 1] || '') : '',
        [FIELD_PRINCIPAL]: idx.principal_email ? String(row.rowData[idx.principal_email - 1] || '') : '',
        [FIELD_RESOURCE]: idx.resource_name ? String(row.rowData[idx.resource_name - 1] || '') : '',
        [FIELD_ROLE]: idx.role ? String(row.rowData[idx.role - 1] || '') : '',
        [FIELD_REASON]: idx.reason ? String(row.rowData[idx.reason - 1] || '') : '',
        [FIELD_APPROVER]: idx.approver_email ? String(row.rowData[idx.approver_email - 1] || '') : ''
      }
    });
  });
  if (emailsToSend.length > 0) {
    sendNotificationEmails_(emailsToSend);
  }

  const summary = [
    `結果: ${result.result || 'UNKNOWN'}`,
    `成功: ${succeeded.length}件`,
    `失敗: ${failed.length}件`
  ];
  if (failed.length > 0) {
    const top3 = failed
      .slice(0, 3)
      .map(item => `${item.request_id}: ${item.error_code || 'ERROR'}`);
    summary.push(`失敗詳細(先頭): ${top3.join(', ')}`);
  }
  ui.alert(summary.join('\n'));
}

function getProcessedHistorySheet_(header) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName('processed_history');
  if (!sheet) {
    sheet = ss.insertSheet('processed_history');
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(header);
  } else {
    const existingHeader = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    const missing = header.filter(name => !existingHeader.includes(name));
    missing.forEach(name => {
      sheet.getRange(1, sheet.getLastColumn() + 1).setValue(name);
    });
  }
  return sheet;
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

function getOidcToken_(props) {
  if (!props.gasInvokerEmail) throw new Error("Missing GAS_INVOKER_SA_EMAIL property");
  const url = `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${props.gasInvokerEmail}:generateIdToken`;
  const audience = props.iapClientId || props.cloudRunUrl.replace(/\/execute\/?$/, '');
  const payload = {
    audience: audience,
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
      'request_group_id', 'request_id', 'request_type', 'principal_email', 'resource_name', 'role',
      'reason', 'expires_at', 'requester_email', 'approver_email', 'status', 'requested_at', 'ticket_ref', COL_AI_SUGGEST
    ]);
  }

  ensureRequestReviewColumns_(sheet);

  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const idx = indexMap_(header);
  let rowData = new Array(header.length).fill('');
  
  if (idx.request_group_id) rowData[idx.request_group_id - 1] = request.request_group_id || request.request_id || '';
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
    gasInvokerEmail: p.getProperty('GAS_INVOKER_SA_EMAIL'),
    iapClientId: p.getProperty('IAP_OAUTH_CLIENT_ID')
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
 * BigQueryの `v_sheet_iam_permission_history` ビューから最新データを直接取得し、
 * `IAM権限設定マトリクス` シートにピボットテーブルを構築します。
 * スプレッドシートのカスタムメニュー（棚卸し > マトリクス更新）から実行可能です。
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
  pullNewRequestsFromBQ_(); // 新規申請を自動プル
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
  const missing = ['request_group_id', 'expires_at', COL_AI_SUGGEST, COL_EXEC_RESULT, COL_FINAL_REFLECT, COL_LAST_CHECKED].filter((name) => !header.includes(name));
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
    const props = getProps_();
    const webAppUrl = props.cloudRunUrl.replace(/\/execute\/?$/, '');
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
    ui.alert('必要なカラムが見つかりません。先に「最新ステータス取得」メニューを実行してください。');
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




function refreshResourcesSheet() {
  refreshSheetFromBigQuery_('リソース', 'v_sheet_resource');
}

function refreshGroupMembersSheet() {
  refreshSheetFromBigQuery_('グループメンバー', 'v_sheet_group_members');
}

function refreshPrincipalsSheet() {
  refreshSheetFromBigQuery_('プリンシパル', 'v_sheet_principal');
}

// マスターシート（プリンシパル・グループメンバー・リソース）を一括更新する関数
function refreshAllMasterData() {
  refreshPrincipalsSheet();
  refreshGroupMembersSheet();
  refreshResourcesSheet();
  SpreadsheetApp.getUi().alert("✅ マスターデータ（プリンシパル・グループメンバー・リソース）の最新化が完了しました。");
}
