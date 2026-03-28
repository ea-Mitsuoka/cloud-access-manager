# BigQuery テーブル定義

このドキュメントは、本プロジェクトで使用されるBigQueryテーブルの一覧、その利用目的、およびスキーマをまとめたものです。情報はTerraform、SQL、Python、Google Apps Scriptのコードベースから直接抽出され、相互参照により正確性を確認済みです。

## テーブル概要

| テーブル名 | 利用目的 |
| :----------------------------------- | :----------------------------------------------------------- |
| `iam_policy_bindings_raw_history` | 特定の時点におけるIAMポリシーバインディングの生データスナップショットを記録する。 |
| `iam_access_requests` | IAMアクセスの申請および承認リクエストを記録し、その現在のステータスを管理する。 |
| `iam_access_change_log` | IAMアクセス変更の実行履歴をログとして記録する。 |
| `iam_access_request_history` | IAMアクセスリクエストのイベント履歴（申請、ステータス変更など）を監査証跡として記録する。 |
| `iam_reconciliation_issues` | 申請されたIAM権限と実際のIAM権限の間の不一致を検出し、記録する。 |
| `iam_pipeline_job_reports` | リソース収集やグループ収集などのパイプラインジョブの実行レポートを記録する。 |
| `principal_catalog` | システム内で参照されるプリンシパルのカタログを管理する。 |
| `google_groups` | Google Workspace/Cloud Identityから収集されたGoogleグループの情報を管理する。 |
| `google_group_membership_history` | Googleグループのメンバーシップ履歴を記録する。 |
| `gcp_resource_inventory_history` | GCPリソース（プロジェクト、フォルダなど）のインベントリ履歴を記録する。 |
| `iam_status_master` | IAM申請のステータスのマスタデータを管理する。 |
| `iam_permission_bindings_history` | IAM権限バインディングの詳細な履歴を記録する。 |
| `iam_permission_matrix` | 各リソースとプリンシパルに対するIAMロールの最新ステータスを一覧表示する。 |
| `iam_policy_permissions` | 現在のIAMポリシーの実際の状態を保持する。 |

______________________________________________________________________

## テーブル詳細

### `iam_policy_bindings_raw_history`

- **利用目的:** 特定の時点におけるIAMポリシーバインディングの生データスナップショットを記録する。リソース棚卸しジョブによって収集される、加工されていないIAM設定の履歴データ。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  assessment_timestamp TIMESTAMP NOT NULL,
  scope STRING,
  resource_type STRING,
  resource_name STRING,
  principal_type STRING,
  principal_email STRING,
  role STRING
  ```
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`

### `iam_access_requests`

- **利用目的:** IAMアクセスの申請および承認リクエストを記録し、その現在のステータスを管理する。
- **スキーマ:**
  ```
  request_id STRING NOT NULL,
  request_type STRING NOT NULL, -- GRANT / REVOKE / CHANGE
  principal_email STRING NOT NULL,
  resource_name STRING NOT NULL,
  role STRING NOT NULL,
  reason STRING,
  expires_at TIMESTAMP,
  requester_email STRING NOT NULL,
  approver_email STRING,
  status STRING NOT NULL, -- PENDING / APPROVED / REJECTED / CANCELLED
  requested_at TIMESTAMP NOT NULL,
  approved_at TIMESTAMP,
  ticket_ref STRING,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
  ```
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`, `apps-script/Code.gs`

### `iam_access_change_log`

- **利用目的:** IAMアクセス変更の実行履歴をログとして記録する。各変更アクション（付与/剥奪）の前後ハッシュ、結果（成功/失敗/スキップ）、エラー情報などを含む。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  request_id STRING NOT NULL,
  action STRING NOT NULL, -- GRANT / REVOKE
  target STRING NOT NULL,
  before_hash STRING,
  after_hash STRING,
  result STRING NOT NULL, -- SUCCESS / FAILED / SKIPPED
  error_code STRING,
  error_message STRING,
  executed_by STRING,
  executed_at TIMESTAMP NOT NULL,
  details JSON
  ```
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`, `apps-script/Code.gs`

### `iam_access_request_history`

- **利用目的:** IAMアクセスリクエストのイベント履歴（申請、ステータス変更など）を監査証跡として記録する。利用目的のスナップショットなども含む。
- **スキーマ:**
  ```
  history_id STRING NOT NULL,
  request_id STRING NOT NULL,
  event_type STRING NOT NULL, -- REQUESTED / STATUS_CHANGED
  old_status STRING,
  new_status STRING NOT NULL,
  reason_snapshot STRING,
  request_type STRING,
  principal_email STRING,
  resource_name STRING,
  role STRING,
  requester_email STRING,
  approver_email STRING,
  acted_by STRING,
  actor_source STRING, -- FORM_SUBMIT / SHEET_EDIT / API
  event_at TIMESTAMP NOT NULL,
  details JSON
  ```
- **主要なソース:** `sql/001_tables.sql`, `apps-script/Code.gs`

### `iam_reconciliation_issues`

- **利用目的:** 申請されたIAM権限と実際のIAM権限の間の不一致（承認済みだが未適用、却下済みだが存在するなど）を検出し、記録する。
- **スキーマ:**
  ```
  issue_id STRING NOT NULL,
  issue_type STRING NOT NULL,
  request_id STRING,
  principal_email STRING,
  resource_name STRING,
  role STRING,
  detected_at TIMESTAMP NOT NULL,
  severity STRING NOT NULL,
  status STRING NOT NULL,
  details JSON
  ```
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`

### `iam_pipeline_job_reports`

- **利用目的:** リソース収集やグループ収集などのパイプラインジョブの実行レポートを記録する。成功/失敗、エラーコード、メッセージ、ヒント、処理件数などの情報を含む。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  job_type STRING NOT NULL, -- RESOURCE_COLLECTION / GROUP_COLLECTION / ...
  result STRING NOT NULL, -- SUCCESS / FAILED_PERMISSION / FAILED
  error_code STRING,
  error_message STRING,
  hint STRING,
  counts JSON,
  details JSON,
  occurred_at TIMESTAMP NOT NULL
  ```
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`

### `principal_catalog`

- **利用目的:** システム内で参照されるプリンシパル（ユーザー、グループ、サービスアカウントなど）のカタログを管理する。
- **スキーマ:**
  ```
  principal_email STRING NOT NULL,
  principal_name STRING,
  principal_type STRING,
  note STRING,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`

### `google_groups`

- **利用目的:** Google Workspace/Cloud Identityから収集されたGoogleグループの情報を管理する。
- **スキーマ:**
  ```
  group_email STRING NOT NULL,
  group_name STRING,
  description STRING,
  source STRING,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

### `google_group_membership_history`

- **利用目的:** Googleグループのメンバーシップ履歴を記録する。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  assessed_at TIMESTAMP NOT NULL,
  group_email STRING NOT NULL,
  member_email STRING NOT NULL,
  member_display_name STRING,
  membership_type STRING,
  source STRING
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

### `gcp_resource_inventory_history`

- **利用目的:** GCPリソース（プロジェクト、フォルダなど）のインベントリ履歴を記録する。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  assessed_at TIMESTAMP NOT NULL,
  resource_type STRING NOT NULL,
  resource_name STRING,
  resource_id STRING NOT NULL,
  parent_resource_id STRING,
  full_resource_path STRING,
  note STRING
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

### `iam_status_master`

- **利用目的:** IAM申請のステータスのマスタデータを管理する。
- **スキーマ:**
  ```
  status_ja STRING NOT NULL,
  status_code STRING,
  description STRING,
  sort_order INT64,
  is_active BOOL NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

### `iam_permission_bindings_history`

- **利用目的:** IAM権限バインディングの詳細な履歴を記録する。帳票用の整形済み履歴として利用される。
- **スキーマ:**
  ```
  execution_id STRING NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  resource_name STRING,
  resource_id STRING,
  resource_full_path STRING,
  principal_email STRING NOT NULL,
  principal_type STRING,
  iam_role STRING NOT NULL,
  iam_condition STRING,
  ticket_ref STRING,
  request_reason STRING,
  status_ja STRING,
  approved_at TIMESTAMP,
  next_review_at DATE,
  approver STRING,
  request_id STRING,
  note STRING
  ```
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

### `iam_permission_matrix`

- **利用目的:** IAM権限設定の履歴からピボットテーブルとして生成され、各リソースとプリンシパルに対するIAMロールの最新ステータスを一覧表示する。
- **スキーマ:**
  ```
  リソース名 (STRING),
  リソースID (STRING),
  プリンシパル (STRING),
  種別 (STRING),
  [DYNAMIC_ROLE_COLUMNS] (STRING - 各ロールのステータスを表す動的カラム)
  ```
- **主要なソース:** `sql/006_matrix_pivot.sql`

### `iam_policy_permissions`

- **利用目的:** 現在のIAMポリシーの実際の状態を保持する。**このテーブルは外部システムによって定期的に更新されることを想定しており、このプロジェクトのコードで`CREATE TABLE`は定義されていません。**
- **スキーマ:** プロジェクトのコード内で`CREATE TABLE`定義がないため、明示的なスキーマは提示できませんが、その使用法から以下のカラムが暗示されます。
  ```
  principal_email STRING,
  resource_name STRING,
  role STRING,
  principal_type STRING,
  resource_id STRING,
  full_resource_path STRING
  ```
- **主要なソース:** `cloud-run/app/repository.py` (参照), 複数のSQLクエリ (参照)
