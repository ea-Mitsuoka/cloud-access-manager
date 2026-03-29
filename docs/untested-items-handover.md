# 未テスト項目 申し送り（開発者/サポート共通）

最終更新日: 2026-03-28

この文書は、実装済みだが未検証の項目を残し、開発者とサポート担当（Codex含む）が同じ前提で引き継ぐためのレジスタです。

## 1. 運用ルール

- 未テスト項目が発生したら、このファイルへ必ず追記する。
- 検証完了したら `状態` を `完了` に更新し、実行ログ（証跡）を残す。
- 仕様変更で再検証が必要になったら `状態` を `再検証待ち` に戻す。
- 口頭連絡だけで終わらせず、必ずこのファイルに反映する。

状態の定義:

- `未着手`: まだ検証していない
- `進行中`: 検証中
- `完了`: 検証完了
- `再検証待ち`: 仕様/コード変更により再確認が必要

## 2. 現在の未テスト項目

| ID | 区分 | 項目 | 想定リスク | 検証手順（最小） | 状態 | 担当 |
|---|---|---|---|---|---|---|
| UT-001 | Apps Script | `Code.gs` 最新版を本番スプレッドシートにデプロイし、`onFormSubmit`/`onEdit` が動くこと | 申請・承認フローが動かない | フォーム送信1件、`requests_review`更新1件で BigQuery 反映を確認 | 未着手 | 開発者 |
| UT-002 | Apps Script | `GeminiRoleAdvisor.gs` Webアプリの動作確認（OAuth権限借用） | 申請前提案UIが使えない | WebアプリURLにアクセスし、提案レスポンス取得を確認 | 未着手 | 開発者 |
| UT-003 | BigQuery | `iam_access_request_history` へ `REQUESTED/STATUS_CHANGED` が記録されること | 利用目的・承認履歴の監査欠落 | 申請→却下/承認を実行し、履歴テーブルをクエリ確認 | 未着手 | 開発者 |
| UT-004 | BigQuery | `v_iam_request_approval_history` の監査ビュー確認 | 監査時に履歴参照できない | ビューから `reason`/`old_status`/`new_status` を取得確認 | 未着手 | 開発者 |
| UT-005 | Terraform | クリーン環境で `bootstrap-tfstate`→`terraform apply` の一連確認 | 初回導入で失敗 | Runbook通りに初回手順を通し、output取得まで確認 | 未着手 | 開発者 |
| UT-006 | Cloud Scheduler | 日次収集ジョブ（組織リソース収集）が自動実行されること | 自動棚卸しが止まる | `test_collectors_flow.py` シナリオテストで自動検証 | 完了 | 開発者 |
| UT-007 | 権限不足時耐性 | リソース収集/グループ収集が権限不足でも全体運用継続できること | 一部失敗で全体停止 | `test_collectors_flow.py` シナリオテストで自動検証 | 完了 | 開発者 |
| UT-008 | Monitoring | Cloud Runでエラー発生時に、設定した通知チャネル（メール/Webhook）へアラートが飛ぶこと | アプリケーション障害に気づけず、SLA違反やデータ不整合につながる | 1. `saas.env` に `ALERT_NOTIFICATION_EMAIL` を設定し `terraform apply`。 <br> 2. `gcloud logging write` 等で意図的に `ERROR` レベルのログをCloud Runサービスに注入。 <br> 3. 設定したメールアドレスに `Cloud Access Manager: Error Detected` アラートが届くことを確認。 | 未着手 | 運用者/開発者 |
| UT-009 | Core Feature | 「緊急」または「緊急付与」キーワードを含む申請が自動承認され、`[BREAK-GLASS]` アラートが即時通知されること | 緊急アクセスが機能しない、または実行が検知されず不正利用のリスクが高まる | 1. `saas.env` に通知先を設定し `terraform apply`。 <br> 2. Googleフォームの申請種別に「緊急」または「緊急付与」を含む選択肢を追加。 <br> 3. 「緊急」または「EMERGENCY」を含む申請でフォームを申請。 <br> 4. BigQueryでステータスが即時 `APPROVED` になっていることを確認。 <br> 5. `iam_access_request_history` に `SYSTEM_AUTO_APPROVE` 承認履歴を確認。 <br> 6. 通知チャネルに `Break-glass...` アラートが届くことを確認。 | 未着手 | 開発者/運用者 |

## 3. 変更時に追加すべき「類似の未テスト項目」

以下に当てはまる変更を入れた場合は、同じ形式で ID を追加してください。

- 外部連携の追加/変更:
  - Google APIs、Cloud Run API、Apps Script Webアプリ、Webhook
- 認可・権限の変更:
  - Terraform IAMロール、SA切替、Secret参照
- データスキーマの変更:
  - BigQueryテーブル/ビュー、履歴列の追加
- 定期実行の変更:
  - Cloud Scheduler、トリガー、バッチSQL
- 承認フロー変更:
  - ステータス遷移、承認条件、再実行条件

## 4. 証跡の残し方（推奨）

- BigQuery:
  - 実行したクエリ
  - 取得結果（件数、代表行）
- Apps Script:
  - 実行ログのスクリーンショットまたはログテキスト
- Cloud Run/Scheduler:
  - 実行時刻、HTTPステータス、エラーメッセージ

この証跡を PR コメントまたは運用チケットに貼り、ID（例: `UT-003`）を紐づける。

## 5. 実施チェックリスト（UT-001 から順番）

実施ルール:

- 原則 `UT-001` から順に実施する。
- 各UTは、チェックを完了したら「実施記録」行を埋める。
- `結果` は `OK / NG / 条件付きOK` で記録する。

### 5.1 UT-001

- [ ] `Code.gs` 最新版を本番スプレッドシートへ反映済み
- [ ] フォーム送信で `iam_access_requests` に1件追加された
- [ ] `requests_review.status` 編集で BigQuery ステータスが更新された

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-001 | | | | | |

### 5.2 UT-002

- [ ] GASに正しいOAuthスコープが設定され、権限承認済みであること
- [ ] デプロイ実行者に `roles/aiplatform.user` が付与されていること（Terraform自動付与の確認）
- [ ] `GeminiRoleAdvisor` Webアプリにアクセス可能
- [ ] 入力に対して提案JSONレスポンスを取得できる

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-002 | | | | | |

### 5.3 UT-003

- [ ] フォーム申請で `REQUESTED` イベントが履歴に記録される
- [ ] 承認または却下で `STATUS_CHANGED` イベントが履歴に記録される
- [ ] `reason_snapshot` に利用目的が保存される

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-003 | | | | | |

### 5.4 UT-004

- [ ] `v_iam_request_approval_history` で履歴を参照できる
- [ ] `reason / old_status / new_status / acted_by / event_at` を確認できる

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-004 | | | | | |

### 5.5 UT-005

- [ ] クリーン環境で `bootstrap-tfstate.sh` が成功
- [ ] `terraform init/plan/apply` が成功
- [ ] 主要output（`cloud_run_url` 等）を取得できる

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-005 | | | | | |

### 5.6 UT-006

- [ ] `iam-resource-inventory-daily` が存在する
- [ ] `iam-group-collection-daily` が存在する
- [ ] 手動実行または次回実行で `pipeline_job_reports` に結果が記録される

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-006 | | | | | |

### 5.7 UT-007

- [ ] 権限不足状態で `/collect/resources` 実行時に `FAILED_PERMISSION` を記録
- [ ] 権限不足状態で `/collect/groups` 実行時に `FAILED_PERMISSION` を記録
- [ ] 失敗後も他フロー（申請承認/照会）が継続可能

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-007 | | | | | |

### 5.8 UT-008

- [ ] `saas.env` に通知先メールアドレスを設定し `terraform apply` 済み
- [ ] `gcloud logging write` コマンドでCloud Runサービスに `severity=ERROR` のログを注入
- [ ] 設定したメールアドレスに `Cloud Access Manager: Error Detected` アラートが届く

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-008 | | | | | |

### 5.9 UT-009

- [ ] Googleフォームの申請種別に「緊急付与」の選択肢を追加済み
- [ ] `saas.env` に通知先を設定し `terraform apply` 済み
- [ ] 「緊急付与」でフォーム申請後、対象権限が即時付与される
- [ ] BigQuery `iam_access_request_history` に `SYSTEM_AUTO_APPROVE` による承認履歴が記録される
- [ ] 設定した通知チャネルに `Break-glass` アラートが届く

実施記録:

| ID | 実施日 | 結果 | 証跡URL | 実施者 | メモ |
|---|---|---|---|---|---|
| UT-009 | | | | | |
