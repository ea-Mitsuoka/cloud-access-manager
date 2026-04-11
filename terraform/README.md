# Terraform

このディレクトリには、Cloud Access ManagerのインフラをプロビジョニングするためのTerraformコードが含まれています。

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

## 環境の安全な削除 (Safe Teardown & Rebuild)

不要になったインフラ（コンピュートリソース）を削除する場合、監査ログや基本API設定などの「ステートフルなリソース」を保護するための専用スクリプトを使用してください。

### 1. 安全な削除 (推奨)

```bash
bash scripts/teardown.sh
```

このスクリプトは以下の処理を全自動で行います。

1. `terraform state rm` を使用して、BigQueryデータセット/テーブル（監査ログ）および有効化済みのGCP API群をTerraformのState管理下から安全に退避させます。
1. その後 `terraform destroy` を実行し、Cloud Run、Scheduler、IAM権限などの「ステートレスなコンピュートリソース」のみを綺麗に削除します。

※ `.tf` ファイルの `prevent_destroy = true` はコード上に維持されたまま、安全にスクラップ＆ビルドが可能です。

### 2. 環境の再構築 (自己修復)

削除後に再度環境を構築する場合は、通常のデプロイスクリプトを実行します。

```bash
bash scripts/bootstrap-deploy.sh
```

デプロイ時、GCP上に残存しているBigQueryリソースやAPI設定を自動検知し、`terraform import` コマンドでTerraformのStateに引き戻してから `apply` を実行します。これにより、過去の監査データを失うことなく、完全な冪等性を持ってシステムが復元されます。

### 3. 完全削除 (非推奨)

プロジェクトそのものを破棄するレベルで、監査ログ（BigQuery）も含めてすべてを完全に削除したい場合は、対象モジュール (`modules/bigquery/main.tf` 等) の `prevent_destroy = true` をコード上から手動で削除し、手動で `terraform destroy` を実行してください。

## 注意事項

- `tool_project_id` は、このツールスタックをデプロイするプロジェクトです。
- `managed_project_id` は、管理対象のプロジェクトです。空 (`""`) の場合は、`tool_project_id` が使用されます。
- `organization_id` はオプションです。空 (`""`) の場合は、このスタックはプロジェクト単体の管理スコープとして扱われます。
- `workspace_customer_id` は、Cloud Identity のグループ検索対象を制御します (デフォルト: `my_customer`)。
- `resource_collection_schedule` は、`/collect/resources` を実行するリソース収集ジョブのスケジュールを制御します。
- `principal_collection_schedule` は、`/collect/principals` を実行するプリンシパル収集ジョブのスケジュールを制御します。
- `iam_policy_collection_schedule` は、`/collect/iam-policies` を実行するIAM権限収集ジョブのスケジュールを制御します。
- `reconciliation_schedule` は、`/reconcile` を実行する不整合検知ジョブのスケジュールを制御します。
- `revoke_expired_permissions_schedule` は、`/revoke_expired_permissions` を実行する期限切れ権限の自動剥奪ジョブのスケジュールを制御します。
- `iam_bindings_history_update_schedule` は、`/jobs/update-iam-bindings-history` を実行する履歴スナップショット更新ジョブのスケジュールを制御します。
- `iam_role_discovery_schedule` は、`/jobs/discover-iam-roles` を実行する未知ロール発見ジョブのスケジュールを制御します。
- `scheduler_time_zone` は、すべてのCloud Schedulerジョブのタイムゾーンを制御します。
- `terraform output management_scope` で選択されている管理スコープを確認できます。
- `terraform output effective_managed_project_id` で現在の管理対象プロジェクトを確認できます。
- `terraform output` で、各スケジューラジョブ名を確認できます (`resource_inventory_scheduler_job`, `principal_collection_scheduler_job` など)。
- 有効化されたAPIは `disable_on_destroy = false` が設定されていることに加え、`teardown.sh` でStateから保護されるため、意図せず無効化されることはありません。
- **重要**: 監査ログとして機能する BigQuery テーブル (`iam_access_requests`, `iam_access_change_log` など) は `lifecycle { prevent_destroy = true }` で保護されています。これにより、誤った `terraform destroy` 操作で監査証跡が失われるのを防ぎます。通常の運用や環境の再構築時は、必ず提供されている `scripts/teardown.sh` と `scripts/bootstrap-deploy.sh` を使用してライフサイクルを管理してください。
- **重要:** GASからのOIDC認証連携を利用する場合、`var.gas_trigger_owner_email` に指定したユーザー（GASトリガーのオーナー）に対して、Terraformが自動的にサービスアカウントトークン作成者ロール（`roles/iam.serviceAccountTokenCreator`）を付与します。これにより、GASスクリプト内から安全にCloud Run呼び出し用のOIDCトークンを動的に生成できるようになります。
- コンテナイメージは別途ビルド/プッシュし、`cloud_run_image` 変数で渡す必要があります。
- 詳細なロール一覧や運用コマンドについては、`docs/operation/operations-runbook.md` を参照してください。
