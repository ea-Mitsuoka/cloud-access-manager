# IAM申請・承認・棚卸し基盤 要件定義

## 1. 目的

- IAM付与申請から承認・実行・棚卸しまでを一気通貫で管理する。
- 既存の `iam_policy_permissions` 収集機能を再利用し、最新可視化と履歴監査を分離する。
- 最小構成は `Googleフォーム + Google Apps Script + Cloud Run + BigQuery` とする。
- インフラ構築は Terraform を必須とする。

## 2. 対象範囲

- 申請受付（Googleフォーム）
- 承認管理（スプレッドシート上のステータス更新）
- IAM変更実行（Cloud Run経由のIAM API）
- 管理表生成（最新状態 + 申請/承認履歴）
- 定期棚卸し（現状の全量洗い出し）

## 3. アーキテクチャ（最小構成）

### 3.1 入力層（Googleフォーム）

- 申請入力UIを提供する。
- フォームの回答先はスプレッドシート（`requests_raw`）とする。
- 必須項目は以下とする。
  - 申請種別（新規付与 / 変更 / 削除）
  - 対象プリンシパル（ユーザー / グループ / SA）
  - 対象リソース（organization/folder/project/resource）
  - 付与・変更ロール（例: `roles/viewer`）
  - 申請理由・利用目的
  - 利用期限（恒久 or 期限日）
  - 申請者メール
  - 承認者メール（または承認グループ）
- 申請前支援として Gemini 提案アシスタント（Apps Script Web アプリ）を併用し、申請者は「やりたいこと」から候補ロールを確認できる。
- Googleフォームには任意JavaScriptボタンを埋め込めないため、フォーム説明欄に Gemini 提案アシスタントURLを配置して導線化する。

### 3.2 審査層（Google Apps Script）

- フォーム回答を整形し、BigQuery `iam_access_requests` に登録する。
- 承認シート（`requests_review`）のステータス変更を検知する。
- `APPROVED` をCloud Runへ通知する。

### 3.3 実行層（Cloud Run）

- `request_id` 単位で冪等実行する。
- `getIamPolicy` で現状取得し差分判定する。
- `setIamPolicy` で `GRANT/REVOKE` を実行する。
- 実行結果をBigQuery `iam_access_change_log` に記録する。

### 3.4 記録・可視化層（BigQuery + 管理表）

- `iam_policy_permissions` は最新スナップショット（洗い替え）として維持する。
- `iam_policy_permissions_history` は履歴（追記）として新設する。
- 申請/承認/実行ログとJOINしたビューを作成し、管理表へ反映する。

## 4. データ要件（BigQuery）

### 4.1 既存テーブル

- `iam_policy_permissions`
  - 用途: 最新スナップショット
  - 更新: `WRITE_TRUNCATE`

### 4.2 新設テーブル

- `iam_policy_permissions_history`

  - 用途: 棚卸し履歴の蓄積
  - 主要列: `execution_id, assessment_timestamp, scope, resource_type, resource_name, principal_type, principal_email, role`
  - 更新: `WRITE_APPEND`

- `iam_access_requests`

  - 用途: 申請・承認の正本
  - 主要列:
    - `request_id`
    - `request_type`（`GRANT/REVOKE/CHANGE`）
    - `principal_email`
    - `resource_name`
    - `role`
    - `reason`
    - `expires_at`
    - `requester_email`
    - `approver_email`
    - `status`（`PENDING/APPROVED/REJECTED/CANCELLED`）
    - `requested_at`
    - `approved_at`
    - `ticket_ref`

- `iam_access_change_log`

  - 用途: API実行監査
  - 主要列:
    - `execution_id`
    - `request_id`
    - `action`（`GRANT/REVOKE`）
    - `target`
    - `before_hash`
    - `after_hash`
    - `result`（`SUCCESS/FAILED/SKIPPED`）
    - `error_code`
    - `error_message`
    - `executed_by`
    - `executed_at`

- `iam_access_request_history`
  - 用途: 申請・承認の監査履歴（利用目的スナップショット含む）
  - 主要列:
    - `history_id`
    - `request_id`
    - `event_type`（`REQUESTED/STATUS_CHANGED`）
    - `old_status`
    - `new_status`
    - `reason_snapshot`
    - `acted_by`
    - `event_at`

- `iam_reconciliation_issues`

  - 用途: 意図（申請）と実態（現状IAM）の不一致管理
  - 主要列: `issue_id, issue_type, request_id, principal_email, resource_name, role, detected_at, severity, status`

## 5. 機能要件

### 5.1 申請登録

- 必須項目未入力は受付不可とする。
- `request_id` は一意採番する。

### 5.2 承認フロー

- 初期ステータスは `PENDING` とする。
- 承認者のみ `APPROVED/REJECTED` を更新可能とする。

### 5.3 IAM実行

- `APPROVED` かつ未実行のみ対象とする。
- 同一 `request_id` の有効実行は1回とする。
- 失敗時の再実行は許可し、履歴は追記する。

### 5.4 管理表更新

- 最新権限: `iam_policy_permissions`
- 申請/承認/実行履歴: `iam_access_requests`, `iam_access_change_log`
- 棚卸し推移: `iam_policy_permissions_history`

### 5.5 定期棚卸し

- 日次または週次で全量収集を行う。
- 不一致を `iam_reconciliation_issues` に記録する。

## 6. 非機能要件

- 監査性: すべての状態変更に `who/when/what` を記録する。
- セキュリティ: 実行SAは最小権限、承認権限と実行権限を分離する。
- 可用性: 再試行設計、失敗時の再送手段を用意する。
- 性能: バッチ実行とAPIクォータ制御を行う。

## 7. 将来拡張方針

- 申請UIをBacklogへ移行可能な構造にする。
- 承認済み申請をGitHub PRに変換し、レビュー統制と監査証跡を強化する。
- 現行BigQueryスキーマは再利用し、入力チャネルだけ差し替える。

## 8. 注意点

- `iam_policy_permissions` は履歴正本にしない。
- `WRITE_TRUNCATE`（最新用）と`WRITE_APPEND`（履歴用）を厳密に分離する。
- すべてのテーブルで `request_id` を追跡キーとして統一する。
- 緊急時の例外付与（Break-glass）フローを別途定義する。
- 期限付き権限の自動剥奪ジョブを用意する。

## 9. 受け入れ条件

- 申請から承認・実行まで手動介入なしで完了できる。
- 実行結果が `iam_access_change_log` に100%記録される。
- 棚卸し実行ごとに `iam_policy_permissions_history` が追記される。
- 管理表で「現在状態」と「履歴」が分離表示される。
- 不整合が `iam_reconciliation_issues` で検知できる。

## 10. MVP実装（このリポジトリ）

### 10.1 ディレクトリ構成

- `sql/001_tables.sql`
  - 必須テーブル（履歴・申請・実行ログ・不整合）DDL
- `sql/004_workbook_tables.sql`
  - 帳票フォーマット準拠のマスタ/履歴テーブル（プリンシパル、グループ、グループメンバー、リソース、ステータス、IAM権限設定履歴）
- `sql/002_views.sql`
  - 管理表向けの結合ビュー
- `sql/005_workbook_views.sql`
  - 帳票の各シートと1対1対応するビュー
- `sql/003_reconciliation.sql`
  - 意図（申請）と実態（現状IAM）の不一致検知バッチ
- `cloud-run/`
  - `POST /execute` で `request_id` を処理する実行API
- `apps-script/Code.gs`
  - Googleフォーム入力と承認シート更新を連携するGAS

### 10.2 3時間実装の進め方（目安）

1. 0:00-0:40
   - ルート直下の `saas.env` を更新（単一設定ファイル）
   - 対話型で実行する場合は `bash scripts/bootstrap-deploy.sh` を実行
   - 手動実行する場合は `bash scripts/sync-config.sh` で各プログラム用設定へ反映し、`cd terraform && terraform init && terraform apply -var-file=../environment.auto.tfvars`
1. 0:40-1:20
   - Cloud Runデプロイ状態を確認（Terraformで作成済み）
   - `POST /healthz` 確認
   - Folder/Project収集は Cloud Scheduler（日次）で自動実行されることを確認
   - Folder/Project収集を実行: `bash scripts/collect-resource-inventory.sh --cloud-run-url <terraform output cloud_run_url>`
   - Googleグループ収集を実行: `bash scripts/collect-google-groups.sh --cloud-run-url <terraform output cloud_run_url>`
1. 1:20-2:10
   - スプレッドシートにフォーム連携
   - `apps-script/Code.gs` 配置、トリガー設定
1. 2:10-2:40
   - `sql/002_views.sql` / `sql/004_workbook_tables.sql` / `sql/005_workbook_views.sql` 実行
   - 管理表タブでビュー参照設定
1. 2:40-3:00
   - `sql/003_reconciliation.sql` を手動実行
   - 1件の承認テスト（`APPROVED` -> Cloud Run -> ログ確認）

### 10.3 実行時の前提

- Cloud Run 実行SAには以下を付与する。
  - `roles/bigquery.dataEditor`（対象dataset単位）
  - `roles/bigquery.jobUser`（tool project）
  - IAM更新対象に応じた最小権限ロール
    - 単一プロジェクト管理: `managed_project_id` に `roles/resourcemanager.projectIamAdmin`
    - 組織管理: `organization_id` に `roles/resourcemanager.projectIamAdmin` + `roles/browser`
- `iam_policy_permissions` は既存の洗い替えジョブを継続利用する。
- `iam_policy_permissions_history` は棚卸しジョブ側で `WRITE_APPEND` する。

### 10.4 MVP制約

- Cloud Run実装は MVPとして `projects/{project_id}` のIAM更新のみ対応。
- `folders/...` `organizations/...` は今後拡張対象（エラーで明示）。
- 認証は `X-Webhook-Token` 共通鍵方式（本番はIngress制限やIAP併用推奨）。
- `organization_id = ""` の場合、`managed_project_id` と一致する `projects/{id}` の申請のみ実行対象とする（対象外は `OUT_OF_SCOPE` で拒否）。
- `organization_id != ""` の場合、Cloud Resource Manager の ancestry で `projects/{id}` が指定組織配下か検証し、対象外は `OUT_OF_SCOPE` で拒否する。

### 10.5 Terraform適用手順

1. `saas.env` の値を環境に合わせる。
   - `tool_project_id`: ツールをデプロイするプロジェクト
   - `managed_project_id`: 管理対象プロジェクト（空なら `tool_project_id` を利用）
   - `organization_id = ""` の場合は「プロジェクト単体管理」として扱う。
1. `bash scripts/sync-config.sh` を実行して、`environment.auto.tfvars` / `cloud-run/.env` / `apps-script/script-properties.json` / `build/sql/*.sql` を生成する。
1. `bash scripts/bootstrap-tfstate.sh` を実行して tfstate 用 GCS バケットを作成/更新する。
1. `terraform/` ディレクトリで以下を実行する。
   - `terraform init -backend-config=../backend.hcl`
   - `terraform plan -var-file=../environment.auto.tfvars`
   - `terraform apply -var-file=../environment.auto.tfvars`
1. `terraform output cloud_run_url` の値を Apps Script の `CLOUD_RUN_EXECUTE_URL` に設定する。
1. `terraform output management_scope` で管理対象スコープを確認する。
1. `terraform output effective_managed_project_id` で実際の管理対象プロジェクトを確認する。
1. `terraform output resource_inventory_scheduler_job` で日次収集ジョブ名を確認する。
1. `terraform output group_collection_scheduler_job` で Googleグループ日次収集ジョブ名を確認する。

## 12. SaaS向け設定一元化

- ルート直下の `saas.env` を単一の設定ソースとして扱う。
- `scripts/sync-config.sh` で設定を各実行ファイル向けに反映する。
  - `environment.auto.tfvars`
  - `cloud-run/.env`
  - `apps-script/script-properties.json`
  - `build/sql/*.sql`（`your_project.your_dataset` を置換済み）
- テンプレートは `saas.env.example` を利用する。
- 対話型のデプロイ支援は `scripts/bootstrap-deploy.sh` を利用する。
- 詳細なロール一覧・bootstrap・運用手順は `docs/operations-runbook.md` を参照する。
- 未テスト項目の申し送り・検証状況は `docs/untested-items-handover.md` を参照する。

## 11. 帳票フォーマット準拠

添付フォーマットに合わせて、以下のシートを BigQuery ビューとして出力できる構成にした。

- `プリンシパル` -> `v_sheet_principal`
- `グループメンバー` -> `v_sheet_group_members`
- `グループ` -> `v_sheet_group`
- `リソース` -> `v_sheet_resource`
- `IAMロール` -> `v_sheet_iam_role`
- `IAM権限設定履歴` -> `v_sheet_iam_permission_history`
- `IAM権限設定マトリクス` -> `IAM権限設定履歴` シートを元に Spreadsheet のピボット機能で生成
- `ステータス` -> `v_sheet_status`
- `カスタムロール` -> `v_sheet_custom_role`

補足:

- ステータスは帳票側（`requests_review` シート）で更新し、Apps Script で BigQuery に同期する。
- `承認済`/`APPROVED` へ更新された場合のみ Cloud Run 実行をトリガーする。
- マトリクスは `refreshIamMatrixPivotFromHistory()` を実行して更新する（データ整形SQLは不要）。
