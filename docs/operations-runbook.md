# IAM Access Manager Runbook

## 1. 必要IAMロール一覧

### 1.1 Cloud Run実行SA（`iam-access-executor@<tool_project>.iam.gserviceaccount.com`）

必須（最小）:
- `roles/bigquery.dataEditor` on `tool_project:dataset`（dataset単位）
- `roles/bigquery.jobUser` on `tool_project`
- `roles/artifactregistry.reader` on `tool_project`（Artifact Registryのプライベートイメージを使う場合）
- `roles/secretmanager.secretAccessor` on webhook secret

管理対象への付与（要件に応じて）:
- `organization_id = ""` の場合:
  - `roles/resourcemanager.projectIamAdmin` on `managed_project_id`（単一プロジェクトのみ）
  - `roles/cloudasset.viewer` on `managed_project_id`（Folder/Project収集）
- `organization_id != ""` の場合:
  - `roles/resourcemanager.projectIamAdmin` on managed organization（配下プロジェクトを許可）
  - `roles/browser` on managed organization（配下判定に必要）
  - `roles/cloudasset.viewer` on managed organization（Folder/Project収集）

Googleグループ収集の前提:
- `cloudidentity.googleapis.com` を有効化
- Workspace/Cloud Identity 側で実行SAにグループ参照権限を付与（組織運用ルールに従う）

### 1.2 Terraform実行主体（開発者 or CI用SA）

必須（`tool_project`）:
- `roles/serviceusage.serviceUsageAdmin`
- `roles/bigquery.admin`
- `roles/run.admin`
- `roles/iam.serviceAccountAdmin`
- `roles/resourcemanager.projectIamAdmin`
- `roles/secretmanager.admin`（webhook secret の作成/更新を行う場合）
- `roles/iam.serviceAccountUser` on executor SA

`tfstate` バケット作成・管理用（初回bootstrap）:
- `roles/storage.admin` on `tool_project`

### 1.3 ロール付与コマンド例

```bash
TOOL_PROJECT_ID="<tool-project-id>"
MANAGED_PROJECT_ID="<managed-project-id>"
ORG_ID="<organization-id-or-empty>"
EXECUTOR_SA="iam-access-executor@${TOOL_PROJECT_ID}.iam.gserviceaccount.com"
WEBHOOK_SECRET_NAME="iam-access-webhook-token"
TF_PRINCIPAL="user:your.name@example.com" # or serviceAccount:ci-terraform@...

# Terraform実行主体
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "$TF_PRINCIPAL" --role roles/serviceusage.serviceUsageAdmin
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "$TF_PRINCIPAL" --role roles/bigquery.admin
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "$TF_PRINCIPAL" --role roles/run.admin
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "$TF_PRINCIPAL" --role roles/iam.serviceAccountAdmin
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "$TF_PRINCIPAL" --role roles/resourcemanager.projectIamAdmin

# Cloud Run実行SA
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/artifactregistry.reader
gcloud secrets add-iam-policy-binding "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/secretmanager.secretAccessor

# organization_idを使う場合のみ
if [[ -n "$ORG_ID" ]]; then
  gcloud organizations add-iam-policy-binding "$ORG_ID" \
    --member "serviceAccount:$EXECUTOR_SA" \
    --role roles/resourcemanager.projectIamAdmin
  gcloud organizations add-iam-policy-binding "$ORG_ID" \
    --member "serviceAccount:$EXECUTOR_SA" \
    --role roles/browser
  gcloud organizations add-iam-policy-binding "$ORG_ID" \
    --member "serviceAccount:$EXECUTOR_SA" \
    --role roles/cloudasset.viewer
else
  gcloud projects add-iam-policy-binding "$MANAGED_PROJECT_ID" \
    --member "serviceAccount:$EXECUTOR_SA" \
    --role roles/resourcemanager.projectIamAdmin
  gcloud projects add-iam-policy-binding "$MANAGED_PROJECT_ID" \
    --member "serviceAccount:$EXECUTOR_SA" \
    --role roles/cloudasset.viewer
fi
```

## 2. tfstate backend bootstrap手順

前提:
- `saas.env` に `TFSTATE_BUCKET`, `TFSTATE_PREFIX`, `TFSTATE_LOCATION` を設定済み
- `saas.env` に `WEBHOOK_SECRET_NAME` を設定済み

実行:
```bash
bash scripts/bootstrap-tfstate.sh
bash scripts/sync-config.sh
cd terraform
terraform init -backend-config=../backend.hcl
```

Webhook secret 作成（初回のみ）:
```bash
TOOL_PROJECT_ID="$(grep '^TOOL_PROJECT_ID=' saas.env | cut -d= -f2)"
WEBHOOK_SECRET_NAME="$(grep '^WEBHOOK_SECRET_NAME=' saas.env | cut -d= -f2)"

gcloud secrets create "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --replication-policy=automatic || true
printf '%s' 'CHANGE_ME_STRONG_RANDOM_TOKEN' | gcloud secrets versions add "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --data-file=-
```

確認:
```bash
gcloud storage buckets describe gs://$(grep '^TFSTATE_BUCKET=' saas.env | cut -d= -f2)
```

## 3. サービスアカウント作成コマンド（手動bootstrapが必要な場合）

通常は Terraform が作成:
- `google_service_account.executor` in `terraform/main.tf`

手動で先に作る場合:
```bash
TOOL_PROJECT_ID="$(grep '^TOOL_PROJECT_ID=' saas.env | cut -d= -f2)"

gcloud iam service-accounts create iam-access-executor \
  --project "$TOOL_PROJECT_ID" \
  --display-name "IAM Access Executor"
```

## 4. コマンド付き運用Runbook

最短導線（対話形式）:
```bash
bash scripts/bootstrap-deploy.sh
```

### 4.1 初回セットアップ
```bash
cp saas.env.example saas.env
# 必要値を編集
bash scripts/bootstrap-tfstate.sh
bash scripts/sync-config.sh
cd terraform
terraform init -backend-config=../backend.hcl
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

### 4.2 反映後の設定
```bash
cd terraform
terraform output cloud_run_url
```
- 出力値を `apps-script/script-properties.json` の `CLOUD_RUN_EXECUTE_URL` に反映

### 4.3 SQL適用（帳票準拠）
```bash
# BigQuery UI か bq query で build/sql/*.sql を順に実行
# 実行順は sql/README.md を参照
```

### 4.4 変更リリース（通常運用）
```bash
bash scripts/sync-config.sh
cd terraform
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

### 4.5 収集ジョブ手動実行（Folder/Project・Googleグループ）
```bash
cd terraform
CLOUD_RUN_URL="$(terraform output -raw cloud_run_url)"

bash ../scripts/collect-resource-inventory.sh --cloud-run-url "$CLOUD_RUN_URL"
bash ../scripts/collect-google-groups.sh --cloud-run-url "$CLOUD_RUN_URL"
```

### 4.6 Cloud Scheduler（日次自動実行）確認
```bash
cd terraform
terraform output resource_inventory_scheduler_job
terraform output group_collection_scheduler_job
gcloud scheduler jobs describe iam-resource-inventory-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-group-collection-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
```

### 4.7 障害時の一次切り分け
```bash
# Cloud Run 実行結果
bq query --use_legacy_sql=false \
"SELECT request_id, result, error_code, error_message, executed_at
 FROM \`$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2).$(grep '^BQ_DATASET_ID=' ../saas.env | cut -d= -f2).iam_access_change_log\`
 ORDER BY executed_at DESC LIMIT 50"
```

```bash
# 収集ジョブの成功/失敗レポート（権限不足は FAILED_PERMISSION）
bq query --use_legacy_sql=false \
"SELECT job_type, result, error_code, hint, occurred_at
 FROM \`$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2).$(grep '^BQ_DATASET_ID=' ../saas.env | cut -d= -f2).pipeline_job_reports\`
 ORDER BY occurred_at DESC LIMIT 50"
```

## 5. 未テスト項目の申し送り運用

- 未テスト事項は `docs/untested-items-handover.md` に記録して管理する。
- 新機能や権限変更を入れた場合は、同ファイルへ項目追加してからリリースする。
- 検証が完了したら、状態を更新して証跡（クエリ結果/ログ）を紐づける。
