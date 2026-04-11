from __future__ import annotations
import json
import logging
import urllib.request
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

GEMINI_MODEL = "gemini-2.5-flash"


def _call_gemini_api(project_id: str, prompt: str, temperature: float = 0.2) -> dict:
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())

        url = (
            f"https://asia-northeast1-aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/asia-northeast1/publishers/google/models/"
            f"{GEMINI_MODEL}:generateContent"
        )

        payload = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req) as response:
            body = json.loads(response.read().decode("utf-8"))

        text = (
            body.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        clean_text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)

    except Exception as e:
        logging.error(f"Gemini API call failed: {e}")
        raise


def suggest_iam_roles(
    project_id: str, goal: str, resource: str, principal: str
) -> dict:
    prompt = (
        "あなたはGoogle CloudのIAMレビュアーです。\n"
        "利用者がやりたいことに対して、最小権限で推奨ロール候補を提案してください。\n"
        "結果は、手短にビジネスライクな文章で、JSONのみで出力してください。\n\n"
        "必須要件:\n- できるだけ基本ロール（Owner/Editor）を避ける\n"
        "- 具体的な事前定義ロール（roles/...）を優先\n"
        "- 不足情報がある場合は確認事項を示す\n\n"
        "入力:\n"
        f"- やりたいこと: {goal}\n"
        f"- 対象リソース: {resource or '(未指定)'}\n"
        f"- 対象プリンシパル: {principal or '(未指定)'}\n\n"
        "JSONスキーマ:\n{\n"
        '  "summary": "一言要約",\n'
        '  "recommended_roles": [\n'
        "    {\n"
        '      "role": "roles/...",\n'
        '      "reason": "理由",\n'
        '      "scope_hint": "project/folder/resource"\n'
        "    }\n"
        "  ],\n"
        '  "cautions": ["注意点1", "注意点2"],\n'
        '  "reviewer_note": "承認者向けメモ"\n}'
    )
    return _call_gemini_api(project_id, prompt, temperature=0.2)


def validate_role_with_ai(project_id: str, role: str, goal: str, resource: str) -> dict:
    prompt = (
        "あなたはGoogle CloudのIAMエキスパートです。\n"
        "ユーザーが申請しようとしているIAMロール名が、"
        "Google Cloudに実際に存在する正確な名称"
        "（タイポや大文字小文字のミスがないか）を厳格に判定してください。\n"
        "結果は必ず以下のJSONフォーマットのみで返してください。"
        "マークダウンやバッククォートは不要です。\n"
        '{"is_valid": boolean, "suggested_role": '
        '"正しいロール名（is_validがfalseの場合のみ推測して出力）"}\n\n'
        f"入力されたロール名: {role}\n"
        f"申請理由・利用目的: {goal or '(未指定)'}\n"
        f"対象リソース: {resource or '(未指定)'}"
    )
    return _call_gemini_api(project_id, prompt, temperature=0.1)
