# Terraform

このディレクトリには、IAM Access ManagerのインフラをプロビジョニングするためのTerraformコードが含まれています。

## モジュール構造

コードは機能ごとにモジュールに分割されています。

- `modules/bigquery`: BigQueryデータセットとテーブルを作成します。
- `modules/service_accounts`: IAM Access ExecutorとScheduler Invokerのサービスアカウントを作成します。
- `modules/cloud_run`: IAM Access ExecutorのCloud Runサービスをデプロイします。
- `modules/scheduler`: Cloud Runサービスを定期的にトリガーするためのCloud Schedulerジョブを作成します。
- `modules/monitoring`: Cloud Runのエラーや緊急アクセスを監視するためのアラートポリシーを作成します。

## 前提条件

- Terraform 1.6+
- ターゲットプロジェクトに対して`gcloud auth`が設定済みであること

## 使い方

### GCSバックエンドを利用する場合（推奨）

1. `backend.hcl` にGCSバケット名などを設定します。
   ```hcl
   bucket = "your-tfstate-bucket-name"
   ```
1. スクリプトを実行してセットアップします。
   ```bash
   bash ../scripts/sync-config.sh
   bash ../scripts/bootstrap-tfstate.sh
   ```
1. Terraformを初期化・実行します。
   ```bash
   cd terraform
   terraform init -backend-config=../backend.hcl
   terraform plan -var-file=../environment.auto.tfvars
   terraform apply -var-file=../environment.auto.tfvars
   ```

### ローカルバックエンドを利用する場合（テスト用）

1. `terraform/backend.tf` ファイル内の `backend "gcs" {}` ブロックをコメントアウトします。
1. Terraformを初期化・実行します。
   ```bash
   cd terraform
   terraform init
   terraform plan -var-file=../environment.auto.tfvars
   terraform apply -var-file=../environment.auto.tfvars
   ```

## 注意事項

- `tool_project_id` は、このツールスタックをデプロイするプロジェクトです。
- `managed_project_id` は、管理対象のプロジェクトです。空 (`""`) の場合は、`tool_project_id` が使用されます。
- `organization_id` はオプションです。空 (`""`) の場合は、このスタックはプロジェクト単体の管理スコープとして扱われます。
- `workspace_customer_id` は、Cloud Identity のグループ検索対象を制御します (デフォルト: `my_customer`)。
- `resource_collection_schedule` は、`/collect/resources` を実行するリソース収集ジョブのスケジュールを制御します。
- `group_collection_schedule` は、`/collect/groups` を実行するグループ収集ジョブのスケジュールを制御します。
- `reconciliation_schedule` は、`/reconcile` を実行する不整合検知ジョブのスケジュールを制御します。
- `revoke_expired_permissions_schedule` は、`/revoke_expired_permissions` を実行する期限切れ権限の自動剥奪ジョブのスケジュールを制御します。
- `iam_bindings_history_update_schedule` は、`/jobs/update-iam-bindings-history` を実行する履歴スナップショット更新ジョブのスケジュールを制御します。
- `scheduler_time_zone` は、すべてのCloud Schedulerジョブのタイムゾーンを制御します。
- `terraform output management_scope` で選択されている管理スコープを確認できます。
- `terraform output effective_managed_project_id` で現在の管理対象プロジェクトを確認できます。
- `terraform output` で、各スケジューラジョブ名を確認できます (`resource_inventory_scheduler_job`, `group_collection_scheduler_job` など)。
- 有効化されたAPIは `lifecycle.prevent_destroy = true` と `disable_on_destroy = false` で保護されているため、`destroy` を実行しても無効化されません。
- **重要**: 監査ログとして機能する BigQuery テーブル (`iam_access_requests`, `iam_access_change_log` など) は `lifecycle { prevent_destroy = true }` で保護されています。これにより、誤った `terraform destroy` 操作で監査証跡が失われるのを防ぎます。これらのテーブルを意図的に削除する必要がある場合は、まずこのライフサイクル設定をコードから削除する必要があります。
- **重要:** Webhook認証に使用されるSecret Managerのシークレット（`var.webhook_secret_name`で指定）は、Terraformによって自動的にプロビジョニングされます。初回デプロイ時に手動で作成する必要はありません。ただし、プロビジョニング後にSecret Managerコンソールから任意の値に変更することができます。
- コンテナイメージは別途ビルド/プッシュし、`cloud_run_image` 変数で渡す必要があります。
- 詳細なロール一覧や運用コマンドについては、`docs/operations-runbook.md` を参照してください。
