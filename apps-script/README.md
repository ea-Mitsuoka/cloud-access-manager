# Apps Script Setup

## 1. Script properties

Set these values in `Project Settings > Script properties`.

- `BQ_PROJECT_ID`
- `BQ_DATASET_ID`
- `BQ_LOCATION`
- `CLOUD_RUN_EXECUTE_URL` (e.g. `https://<service-url>/execute`)
- `WEBHOOK_SHARED_SECRET` (optional but recommended)
- `GEMINI_API_KEY` (Gemini提案アシスタントを使う場合に必須)

You can generate this as JSON from root config via:

```bash
bash scripts/sync-config.sh
cat apps-script/script-properties.json
```

## 2. Enable services

- `Services` -> add `BigQuery API` (Advanced Google Services)
- In linked Google Cloud project, also enable BigQuery API

## 3. Triggers

Create installable triggers:

- `onFormSubmit`: From spreadsheet, Event source `From spreadsheet`, Event type `On form submit`
- `onEdit`: From spreadsheet, Event source `From spreadsheet`, Event type `On edit`

`onEdit` behavior:
- When `requests_review.status` is updated, status is synchronized to BigQuery.
- If edited status is `承認済` or `APPROVED`, Cloud Run `/execute` is called automatically.
- After status update, `実行結果 / 最終反映確認 / 最終確認時刻` are refreshed in `requests_review`.
- `利用目的` は申請・承認履歴テーブル `iam_access_request_history` にスナップショット保存されます（監査向け）。

Pivot operation (no data shaping):
- Run `refreshIamMatrixPivotFromHistory()` to generate `IAM権限設定マトリクス` directly from `IAM権限設定履歴` using native spreadsheet pivot tables.
- A custom menu is also available: `棚卸し > マトリクス更新`.

Review status sync:
- Run `refreshRequestReviewStatus_()` to refresh `requests_review` from BigQuery execution/actual IAM state.
- A custom menu is also available: `棚卸し > 申請反映ステータス更新`.
- Recommended trigger: time-driven (e.g. every 15 minutes) for continuous visibility.

## 4. Required form item labels

This script reads the following Japanese labels from form answers:

- `申請種別`
- `対象プリンシパル`
- `対象リソース`
- `付与・変更ロール`
- `申請理由・利用目的`
- `申請者メール`
- `承認者メール（または承認グループ）`

If your labels differ, update keys inside `pick_()` calls in `Code.gs`.

`申請理由・利用目的` は承認判断の必須情報として扱われ、未入力は受け付けません。

## 5. Gemini提案アシスタント（申請前支援）

申請者がIAMロール名を知らなくても、「Google Cloudでやりたいこと」から候補ロールを事前に確認できます。

1. Apps Script に `GeminiRoleAdvisor.gs` と `RoleAdvisor.html` を配置する
1. `Project Settings > Script properties` に `GEMINI_API_KEY` を設定する
1. Apps Script を Web アプリとしてデプロイする（実行ユーザー: 自分、アクセス: 組織内ユーザー）
1. 発行された Web アプリURLを Googleフォームの説明文に貼る
1. 申請者は URL 先で提案を取得し、`付与・変更ロール` と `申請理由・利用目的` に転記して送信する

注記:
- Googleフォーム本体に任意JavaScriptの「ボタン」を直接埋め込むことはできません。運用上はフォーム説明欄のリンク導線で代替します。
- Geminiの提案は参考情報です。最終承認は管理者が行ってください。

## 6. Troubleshooting (Apps Script)

- `棚卸し` メニューが表示されない:
  - スプレッドシートを再読み込みしてください（`onOpen` は再読込時に実行されます）。
  - Apps Script の保存漏れがないか確認してください。
  - 初回はスクリプトの権限承認ダイアログ完了後に再読み込みが必要です。

- Gemini提案アシスタントでエラーになる:
  - `GEMINI_API_KEY` が Script Properties に設定されているか確認してください。
  - Webアプリのデプロイ版が最新コードになっているか確認してください（再デプロイ）。

- `マトリクス更新` 実行でエラーになる:
  - `IAM権限設定履歴` シート名が完全一致しているか確認してください。
  - ヘッダーに `リソース名 / リソースID / プリンシパル / 種別 / IAMロール / ステータス` があるか確認してください。

- トリガーが動かない:
  - Installable trigger（`onFormSubmit`, `onEdit`, 必要に応じて `refreshRequestReviewStatus_` の時間トリガー）を作成済みか確認してください。
  - `Project Settings > Script properties` の必須値（`BQ_PROJECT_ID`, `BQ_DATASET_ID`, `BQ_LOCATION`, `CLOUD_RUN_EXECUTE_URL`）を確認してください。

- BigQuery 関連の権限エラー:
  - Apps Script 側で `BigQuery API`（Advanced Service）を有効化しているか確認してください。
  - 紐づく GCP プロジェクトでも BigQuery API が有効か確認してください。

申し送り:
- 未テスト項目や検証結果は `docs/untested-items-handover.md` に記録してください。
