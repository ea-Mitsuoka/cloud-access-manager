from __future__ import annotations
import json
import logging
import urllib.request
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest


def translate_roles_with_gemini(project_id: str, roles: list[str]) -> dict[str, str]:
    """Gemini API を用いて IAMロール名の日本語訳を推測します。"""
    if not roles:
        return {}
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())
        token = credentials.token

        url = (
            "https://asia-northeast1-aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/asia-northeast1/publishers/google/models/"
            "gemini-2.5-flash:generateContent"
        )
        prompt = (
            "あなたはGoogle CloudのIAMエキスパートです。\n"
            "以下のIAMロールIDのリストを受け取り、Google Cloudの公式ドキュメントに準拠した自然で\n"
            "分かりやすい日本語の役割名（10〜20文字程度）に翻訳してください。\n"
            "カスタムロールと思われるものも、単語から用途を推測して日本語化してください。\n"
            "出力は必ず以下のJSONフォーマット（マークダウンなし、プレーンテキスト）のみを返してください。\n"
            '{"roles": [{"role_id": "roles/viewer", "role_name_ja": "閲覧者"}]}\n\n'
            "対象ロールIDリスト:\n" + "\n".join(f"- {r}" for r in roles)
        )
        payload = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
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
        parsed = json.loads(clean_text)

        result = {}
        for item in parsed.get("roles", []):
            if "role_id" in item and "role_name_ja" in item:
                result[item["role_id"]] = item["role_name_ja"]
        return result
    except Exception as e:
        logging.error(f"Failed to translate roles via Gemini: {e}")
        return {}
