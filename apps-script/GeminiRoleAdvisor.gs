/**
 * Gemini role advisor for requesters (pre-submit helper).
 *
 * Deploy as Web App and link URL from Google Form description.
 * Script Properties required:
 * - GEMINI_API_KEY
 */

const GEMINI_MODEL = 'gemini-2.5-flash';

function doGet() {
  return HtmlService.createHtmlOutputFromFile('RoleAdvisor')
    .setTitle('IAMロール提案アシスタント')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function suggestIamRoles(input) {
  const oauthToken = ScriptApp.getOAuthToken();
  const project = PropertiesService.getScriptProperties().getProperty('BQ_PROJECT_ID');
  if (!project) {
    throw new Error('missing script property: BQ_PROJECT_ID');
  }

  const goal = String(input.goal || '').trim();
  const resource = String(input.resource || '').trim();
  const principal = String(input.principal || '').trim();

  if (!goal) {
    throw new Error('goal is required');
  }

  const prompt = buildPrompt_(goal, resource, principal);
  const url = `https://asia-northeast1-aiplatform.googleapis.com/v1/projects/${project}/locations/asia-northeast1/publishers/google/models/${GEMINI_MODEL}:generateContent`;

  const payload = {
    contents: [{
      role: 'user',
      parts: [{ text: prompt }]
    }],
    generationConfig: {
      temperature: 0.2,
      responseMimeType: 'application/json'
    }
  };

  const resp = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: `Bearer ${oauthToken}`
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const code = resp.getResponseCode();
  const text = resp.getContentText();
  if (code >= 300) {
    throw new Error(`Gemini API failed (${code}): ${text}`);
  }

  const body = JSON.parse(text);
  const candidate = body.candidates && body.candidates[0];
  const out = candidate && candidate.content && candidate.content.parts && candidate.content.parts[0] && candidate.content.parts[0].text;
  if (!out) {
    throw new Error('Gemini response is empty');
  }

  const parsed = JSON.parse(out);
  return {
    summary: parsed.summary || '',
    recommended_roles: parsed.recommended_roles || [],
    cautions: parsed.cautions || [],
    reviewer_note: parsed.reviewer_note || ''
  };
}

function buildPrompt_(goal, resource, principal) {
  return [
    'あなたはGoogle CloudのIAMレビュアーです。',
    '利用者がやりたいことに対して、最小権限で推奨ロール候補を提案してください。',
    '結果はJSONのみで出力してください。',
    '',
    '必須要件:',
    '- できるだけ基本ロール（Owner/Editor）を避ける',
    '- 具体的な事前定義ロール（roles/...）を優先',
    '- 不足情報がある場合は確認事項を示す',
    '',
    '入力:',
    `- やりたいこと: ${goal}`,
    `- 対象リソース: ${resource || '(未指定)'}`,
    `- 対象プリンシパル: ${principal || '(未指定)'}`,
    '',
    'JSONスキーマ:',
    '{',
    '  "summary": "一言要約",',
    '  "recommended_roles": [',
    '    {"role": "roles/...", "reason": "理由", "scope_hint": "project/folder/resource"}',
    '  ],',
    '  "cautions": ["注意点1", "注意点2"],',
    '  "reviewer_note": "承認者向けメモ"',
    '}'
  ].join('\n');
}
