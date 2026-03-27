# IAM Access Manager 運用手順書

## 1. 運用モードについて

本システムは、`saas.env`の`organization_id`の設定に応じて、2つの主要な運用モードで動作します。

### 1.1 Organizationモード

- **設定:** `organization_id`にGCP組織のID（例: `123456789012`）を設定します。
- **動作:** システムは組織全体を管理対象とします。フォルダ階層を含むリソースの棚卸しや、組織全体のIAMポリシーの変更、Googleグループの収集が可能です。
- **権限:** 実行サービスアカウントには、組織レベルでの複数のIAMロール（`roles/resourcemanager.projectIamAdmin`, `roles/resourcemanager.folderAdmin`, `roles/cloudasset.viewer`など）の付与が必要です。

### 1.2 Project-onlyモード

- **設定:** `organization_id`を空 (`""`) にします。
- **動作:** システムの機能は、`managed_project_id`で指定された単一のGoogle Cloudプロジェクトに限定されます。お客様が組織全体の権限を許可しないSaaS提供形態などに適しています。
- **権限と制限:**
  - 必要な権限は、対象プロジェクトに対する`roles/resourcemanager.projectIamAdmin`と`roles/cloudasset.viewer`などに限定されます。
  - IAMの変更は、そのプロジェクト内でのみ可能です。
  - リソース棚卸しも、プロジェクト内のリソースのみが対象です。
  - **Googleグループ収集機能は、組織/ワークスペースレベルの権限を必要とするため、このモードでは正常に動作しない可能性が高いです。**

______________________________________________________________________

## 2. 必要IAMロール一覧

### 2.1 Cloud Run実行サービスアカウント

（`iam-access-executor@<tool_project>.iam.gserviceaccount.com`）

**必須（最小）:**

- `roles/bigquery.dataEditor` on `tool_project:dataset`（dataset単位）
- `roles/bigquery.jobUser` on `tool_project`
- `roles/artifactregistry.reader` on `tool_project`（Artifact Registryのプライベートイメージを使う場合）
- `roles/secretmanager.secretAccessor` on webhook secret

**管理対象への付与（要件に応じて）:**

- `organization_id = ""` の場合:
  - `roles/resourcemanager.projectIamAdmin` on `managed_project_id`（単一プロジェクトのみ）
  - `roles/cloudasset.viewer` on `managed_project_id`（Folder/Project収集）
- `organization_id != ""` の場合:
  - `roles/resourcemanager.projectIamAdmin` on managed organization（配下プロジェクトを許可）
  - `roles/browser` on managed organization（配下判定に必要）
  - `roles/cloudasset.viewer` on managed organization（Folder/Project収集）

**Googleグループ収集の前提:**

- `cloudidentity.googleapis.com` を有効化
- Workspace/Cloud Identity 側で実行SAにグループ参照権限を付与（組織運用ルールに従う）

### 2.2 Terraform実行主体（開発者またはCI用サービスアカウント）

**必須（`tool_project`に対して）:**

- `roles/serviceusage.serviceUsageAdmin`
- `roles/bigquery.admin`
- `roles/run.admin`
- `roles/iam.serviceAccountAdmin`
- `roles/resourcemanager.projectIamAdmin`
- `roles/secretmanager.admin`（webhook secret の作成/更新を行う場合）
- `roles/iam.serviceAccountUser` on executor SA

**`tfstate` バケット作成・管理用（初回ブートストラップ）:**

- `roles/storage.admin` on `tool_project`

**VPC-SC有効化に特有の権限 (組織レベルで必要):**

- `roles/accesscontextmanager.policyAdmin`
- `roles/resourcemanager.organizationAdmin`

### 2.3 ロール付与コマンド例

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

# (VPC-SC有効化時のみ) Terraform実行主体に組織レベルの権限を付与
# gcloud organizations add-iam-policy-binding "$ORG_ID" --member "$TF_PRINCIPAL" --role roles/accesscontextmanager.policyAdmin
# gcloud organizations add-iam-policy-binding "$ORG_ID" --member "$TF_PRINCIPAL" --role roles/resourcemanager.organizationAdmin

# Cloud Run実行サービスアカウント
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/artifactregistry.reader
gcloud secrets add-iam-policy-binding "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --member "serviceAccount:$EXECUTOR_SA" --role roles/secretmanager.secretAccessor

# organization_idを使う場合のみ
if [[ -n "$ORG_ID" ]]; then
  gcloud organizations add-iam-policy-binding "$ORG_ID" 
    --member "serviceAccount:$EXECUTOR_SA" 
    --role roles/resourcemanager.projectIamAdmin
  gcloud organizations add-iam-policy-binding "$ORG_ID" 
    --member "serviceAccount:$EXECUTOR_SA" 
    --role roles/browser
  gcloud organizations add-iam-policy-binding "$ORG_ID" 
    --member "serviceAccount:$EXECUTOR_SA" 
    --role roles/cloudasset.viewer
else
  gcloud projects add-iam-policy-binding "$MANAGED_PROJECT_ID" 
    --member "serviceAccount:$EXECUTOR_SA" 
    --role roles/resourcemanager.projectIamAdmin
  gcloud projects add-iam-policy-binding "$MANAGED_PROJECT_ID" 
    --member "serviceAccount:$EXECUTOR_SA" 
    --role roles/cloudasset.viewer
fi
```

## 3. CI/CD (GitHub Actions) の設定

`.github/workflows/ci.yml` に定義されたCI/CDパイプラインを完全に機能させるには、`README.md`の「CI/CD」セクションで説明されている設定が必要です。具体的には、GitHubリポジトリにSecretとVariableを設定してください。

### 3.1 Workload Identity Federationの設定（参考）

CIジョブがGoogle Cloudリソースを操作するために、パスワードレス認証であるWorkload Identity Federation（WIF）を設定する手順の参考例です。

1. **CI用のサービスアカウント作成:**

   ```bash
   gcloud iam service-accounts create iam-access-ci-sa 
     --project="${TOOL_PROJECT_ID}" 
     --display-name="IAM Access CI/CD"
   ```

1. **WIFプールとプロバイダの作成:**

   ```bash
   # プールの作成
   gcloud iam workload-identity-pools create "github-pool" 
     --project="${TOOL_PROJECT_ID}" 
     --location="global" 
     --display-name="GitHub Actions Pool"

   # プールのIDを取得
   WORKLOAD_IDENTITY_POOL_ID=$(gcloud iam workload-identity-pools describe "github-pool" --project="${TOOL_PROJECT_ID}" --location="global" --format="value(name)")

   # プロバイダの作成
   gcloud iam workload-identity-pools providers create-oidc "github-provider" 
     --project="${TOOL_PROJECT_ID}" 
     --location="global" 
     --workload-identity-pool="github-pool" 
     --display-name="GitHub Actions Provider" 
     --issuer-uri="https://token.actions.githubusercontent.com" 
     --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository"
   ```

1. **CI用サービスアカウントへの権限付与:**
   CI用サービスアカウントがリポジトリの `main` ブランチからの操作のみを受け付けるように設定します。

   ```bash
   REPO="your-github-organization/your-repository-name" # 例: "google-cloud-japan/cloud-access-manager"
   CI_SA_EMAIL="iam-access-ci-sa@${TOOL_PROJECT_ID}.iam.gserviceaccount.com"

   gcloud iam service-accounts add-iam-policy-binding "${CI_SA_EMAIL}" 
     --project="${TOOL_PROJECT_ID}" 
     --role="roles/iam.workloadIdentityUser" 
     --member="principalSet://iam.googleapis.com/${WORKLOAD_IDENTITY_POOL_ID}/subject/repo/${REPO}:ref:refs/heads/main"
   ```

1. **CI用サービスアカウントに必要なロールを付与:**
   CI用サービスアカウントには、Terraformの実行、Dockerイメージのビルドとプッシュに必要な権限が必要です。これは、「2.2 Terraform実行主体」と同様の権限セットになります。

   ```bash
   # (例)
   gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$CI_SA_EMAIL" --role roles/run.admin
   gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$CI_SA_EMAIL" --role roles/storage.admin # for tfstate
   gcloud projects add-iam-policy-binding "$TOOL_PROJECT_ID" --member "serviceAccount:$CI_SA_EMAIL" --role roles/artifactregistry.writer
   # ... その他Terraformが必要とするロール
   ```

1. **GitHub Secretの設定:**
   リポジトリの `Settings > Secrets and variables > Actions` で、以下のSecretを設定します。

   - `WIF_PROVIDER`: `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider` の形式。
   - `WIF_SERVICE_ACCOUNT`: 上記で作成したCI用SAのメールアドレス (`iam-access-ci-sa@...`)。

### 3.2 Artifact Registryリポジトリ

CIパイプラインは、`iam-access-repo` という名前のArtifact RegistryリポジトリにDockerイメージをプッシュします。このリポジトリが存在しない場合は作成してください。

```bash
gcloud artifacts repositories create iam-access-repo 
  --repository-format=docker 
  --location=${REGION} 
  --project=${TOOL_PROJECT_ID}
```

もし異なる名前のリポジトリを使用する場合は、`.github/workflows/ci.yml` 内のイメージ名を更新してください。

## 4. 高度なセキュリティ設定 (VPC-SC)

本システムはオプションで、VPC Service Controls (VPC-SC) を有効にして、Cloud Runサービスと関連APIをサービス境界で保護する機能を提供します。

### 4.1 機能概要

- **Cloud Run Ingress制限:** `enable_vpc_sc = true` の場合、Cloud Runへのアクセスは内部トラフィックおよびロードバランサ経由に限定されます。
- **サービス境界の構築:** `tool_project` を含むサービス境界が作成され、Cloud Run, BigQuery, Secret ManagerなどのAPIへのアクセスが境界内からに制限されます。

### 4.2 有効化手順

1. **`saas.env` の設定:**

   - `enable_vpc_sc` を `true` に設定します。
   - `access_policy_name` に、親となるアクセスポリシー名 (例: `accessPolicies/123456789012`) を設定します。

1. **Terraformの適用:**
   `bash scripts/sync-config.sh` を実行後、`terraform apply` を実行します。`bootstrap-deploy.sh`の対話形式でも設定可能です。

### 4.3 運用上の注意と必須権限

- **デフォルトは無効:** `enable_vpc_sc` はデフォルトで `false` のため、既存環境への影響はありません。
- **必須権限:** VPC-SCは組織リソースのため、Terraform実行主体には**組織レベル**で以下のIAMロールが**両方とも必要**です。権限がない場合、`terraform apply`は失敗します。対話形式のデプロイスクリプト `scripts/bootstrap-deploy.sh` は、VPC-SC有効化の際にこの権限付与を支援します。
  - **Access Context Manager 管理者 (`roles/accesscontextmanager.policyAdmin`)**
  - **組織管理者 (`roles/resourcemanager.organizationAdmin`)**

## 5. tfstateバックエンドのブートストラップ手順

**前提:**

- `saas.env` に `TFSTATE_BUCKET`, `TFSTATE_PREFIX`, `TFSTATE_LOCATION` を設定済み
- `saas.env` に `WEBHOOK_SECRET_NAME` を設定済み

**実行:**

```bash
bash scripts/bootstrap-tfstate.sh
bash scripts/sync-config.sh
cd terraform
terraform init -backend-config=../backend.hcl
```

**Webhook secretの作成（初回のみ）:**

```bash
TOOL_PROJECT_ID="$(grep '^TOOL_PROJECT_ID=' saas.env | cut -d= -f2)"
WEBHOOK_SECRET_NAME="$(grep '^WEBHOOK_SECRET_NAME=' saas.env | cut -d= -f2)"

gcloud secrets create "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --replication-policy=automatic || true
printf '%s' 'CHANGE_ME_STRONG_RANDOM_TOKEN' | gcloud secrets versions add "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --data-file=-
```

**確認:**

```bash
gcloud storage buckets describe gs://$(grep '^TFSTATE_BUCKET=' saas.env | cut -d= -f2)
```

## 6. サービスアカウント作成コマンド（手動ブートストラップが必要な場合）

通常は Terraform が作成します (`google_service_account.executor` in `terraform/main.tf`)。

手動で先に作成する場合:

```bash
TOOL_PROJECT_ID="$(grep '^TOOL_PROJECT_ID=' saas.env | cut -d= -f2)"

gcloud iam service-accounts create iam-access-executor 
  --project "$TOOL_PROJECT_ID" 
  --display-name "IAM Access Executor"
```

## 7. コマンド付き運用手順書

**最短導線（対話形式）:**

```bash
bash scripts/bootstrap-deploy.sh
```

### 7.1 初回セットアップ

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

### 7.2 反映後の設定

```bash
cd terraform
terraform output cloud_run_url
```

- 出力値を `apps-script/script-properties.json` の `CLOUD_RUN_EXECUTE_URL` に反映します。

### 7.3 SQL適用（帳票準拠）

```bash
# BigQuery UI か bq query で build/sql/*.sql を順に実行
# 実行順は sql/README.md を参照
```

### 7.4 変更リリース（通常運用）

```bash
bash scripts/sync-config.sh
cd terraform
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

### 7.5 収集ジョブ手動実行（フォルダ/プロジェクト・Googleグループ）

```bash
cd terraform
CLOUD_RUN_URL="$(terraform output -raw cloud_run_url)"

bash ../scripts/collect-resource-inventory.sh --cloud-run-url "$CLOUD_RUN_URL"
bash ../scripts/collect-google-groups.sh --cloud-run-url "$CLOUD_RUN_URL"
```

### 7.6 Cloud Scheduler（日次自動実行）確認

```bash
cd terraform
terraform output resource_inventory_scheduler_job
terraform output group_collection_scheduler_job
gcloud scheduler jobs describe iam-resource-inventory-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-group-collection-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
```

### 7.7 障害時の一次切り分け

```bash
# Cloud Run 実行結果
bq query --use_legacy_sql=false 
"SELECT request_id, result, error_code, error_message, executed_at
 FROM `$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2).$(grep '^BQ_DATASET_ID=' ../saas.env | cut -d= -f2).iam_access_change_log`
 ORDER BY executed_at DESC LIMIT 50"
```

```bash
# 収集ジョブの成功/失敗レポート（権限不足は FAILED_PERMISSION）
bq query --use_legacy_sql=false 
"SELECT job_type, result, error_code, hint, occurred_at
 FROM `$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2).$(grep '^BQ_DATASET_ID=' ../saas.env | cut -d= -f2).pipeline_job_reports`
 ORDER BY occurred_at DESC LIMIT 50"
```

## 8. 未テスト項目の申し送り運用

- 未テスト事項は `docs/untested-items-handover.md` に記録して管理します。
- 新機能や権限変更を入れた場合は、同ファイルへ項目追加してからリリースします。
- 検証が完了したら、状態を更新して証跡（クエリ結果/ログ）を紐づけます。
