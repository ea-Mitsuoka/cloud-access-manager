# Terraform

## 前提条件

- Terraform 1.6+
- ターゲットプロジェクトに対して`gcloud auth`が設定済みであること

## 使い方

```bash
bash ../scripts/sync-config.sh
bash ../scripts/bootstrap-tfstate.sh
cd terraform
terraform init -backend-config=../backend.hcl
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

## 注意事項

- `tool_project_id` は、このツールスタックをデプロイするプロジェクトです。
- `managed_project_id` は、管理対象のプロジェクトです。空 (`""`) の場合は、`tool_project_id` が使用されます。
- `organization_id` はオプションです。空 (`""`) の場合は、このスタックはプロジェクト単体の管理スコープとして扱われます。
- `workspace_customer_id` は、Cloud Identity のグループ検索対象を制御します (デフォルト: `my_customer`)。
- `resource_collection_schedule` は、`/collect/resources` を実行する日次のCloud Schedulerの実行スケジュールを制御します。
- `group_collection_schedule` は、`/collect/groups` を実行する日次のCloud Schedulerの実行スケジュールを制御します。
- `scheduler_time_zone` は、両方のCloud Schedulerジョブのタイムゾーンを制御します。
- `terraform output management_scope` で選択されている管理スコープを確認できます。
- `terraform output effective_managed_project_id` で現在の管理対象プロジェクトを確認できます。
- `terraform output resource_inventory_scheduler_job` でリソース収集のスケジューラジョブ名を確認できます。
- `terraform output group_collection_scheduler_job` でグループ収集のスケジューラジョब名を確認できます。
- 有効化されたAPIは `lifecycle.prevent_destroy = true` と `disable_on_destroy = false` で保護されているため、`destroy` を実行しても無効化されません。
- このMVP（Minimum Viable Product）では、データセット、必要なBigQueryテーブル、実行用サービスアカウント、Cloud Runサービスが作成されます。
- 実行用サービスアカウントのIAM権限は、最小権限の原則に基づき、データセットレベルのBigQuery編集者権限と、管理対象スコープ（`managed_project_id` または `organization_id`）に限定されています。
- コンテナイメージは別途ビルド/プッシュし、`cloud_run_image` 変数で渡す必要があります。
- 詳細なロール一覧や運用コマンドについては、`docs/operations-runbook.md` を参照してください。
