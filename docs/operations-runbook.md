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

## 4. アラートと監視 (プロアクティブな異常検知)

本システムは、Cloud Runアプリケーションでエラーが発生した際に、管理者にプロアクティブに通知するためのアラート機能を備えています。

### 4.1 機能概要

- **検知対象:** Cloud Runサービスで`ERROR`レベル以上のログが出力された場合。これには、アプリケーションが明示的に補足した例外（権限不足、APIエラー等）が含まれます。
- **通知方法:** GCPのCloud Monitoringがログを監視し、設定された通知チャネル（メール、OIDC等）にアラートを送信します。
- **冪等性:** 通知先の設定はTerraformで管理され、設定の有無に応じて通知チャネルとアラートポリシーが動的に作成・更新されます。

### 4.2 設定方法

アラートの通知先は、`saas.env`ファイルで設定します。Terraformはこのファイルを読み込み、必要なGCPリソースを自動で構成します。

1. **`saas.env`の編集:**
   以下の変数を設定します。どちらか一方、または両方の設定が可能です。何も設定しない場合、アラート機能は無効になります。

   ```sh
   # Monitoring Alerts (Optional)
   ALERT_NOTIFICATION_EMAIL="your-admin@example.com"
   ALERT_NOTIFICATION_WEBHOOK_URL="https://hooks.slack.com/services/..."
   ```

1. **Terraformの適用:**
   `saas.env`を保存した後、設定をインフラに反映させます。

   ```bash
   bash scripts/sync-config.sh
   cd terraform
   terraform apply
   ```

### 4.3 確認方法

Terraform適用後、GCPコンソールの **[Monitoring] > [アラート]** に移動します。

- **ポリシー:** `IAM Access Manager: Error Detected` という名前のアラートポリシーが作成されていることを確認します。
- **通知チャネル:** ポリシーの詳細画面から、設定したメールアドレスやOIDCに対応する通知チャネルが作成され、ポリシーに紐づいていることを確認できます。

### 4.4 特別アラート: 緊急アクセス（Break-glass）の検知と運用上の注意

通常のエラー検知とは別に、システムは「緊急アクセス（Break-glass）」が実行されたことを検知し、最高レベルの警告を通知する専用のアラートを備えています。

- **検知対象とトリガー:** Googleフォームで「**申請種別**」に\*\*「緊急」**または**「緊急付与」\*\*のキーワードが含まれる選択肢が選ばれた場合、または入力された場合。システムはこれを検知し、Cloud Runのログに `[BREAK-GLASS]` というマーカーを出力します。
  - **重要:** フォームの選択肢に「緊急」や「緊急付与」を追加する作業は、このシステムのデプロイとは別に、**Googleフォーム側で手動で実施する必要**があります。
- **通知:** このログを検知すると、`IAM Access Manager: Break-glass (Emergency) Access Detected` という件名で、`ALERT_NOTIFICATION_EMAIL` や `ALERT_NOTIFICATION_WEBHOOK_URL` に設定されたすべてのチャネルに即時通知が送信されます。
- **目的:** 緊急アクセスは人間の承認プロセスをスキップし、強力な権限を即時付与する機能です。その実行をすべての管理者が即座に認知し、意図された正当な操作であるか、あるいは不適切な利用でないかを、監査目的で確認できるようにすることが目的です。
- **運用上の注意:**
  - 緊急アクセスは、通常の承認フローでは対応できない**インシデント対応時など、真に緊急な状況でのみ利用**すべきです。
  - 緊急アクセスを利用した場合は、後日必ずその妥当性を確認し、詳細な記録を残すなどの**運用プロセスを別途定める**必要があります。
  - この機能は、**監査証跡を完全に残しつつ、緊急時の権限付与を迅速化する**ためのものであり、安易な利用を推奨するものではありません。

## 5. 高度なセキュリティ設定 (VPC-SC)

本システムはオプションで、VPC Service Controls (VPC-SC) を有効にして、Cloud Runサービスと関連APIをサービス境界で保護する機能を提供します。

### 5.1 機能概要

- **Cloud Run Ingress制限:** `enable_vpc_sc = true` の場合、Cloud Runへのアクセスは内部トラフィックおよびロードバランサ経由に限定されます。
- **サービス境界の構築:** `tool_project` を含むサービス境界が作成され、Cloud Run, BigQuery, Secret ManagerなどのAPIへのアクセスが境界内からに制限されます。

### 5.2 有効化手順

1. **`saas.env` の設定:**

   - `enable_vpc_sc` を `true` に設定します。
   - `access_policy_name` に、親となるアクセスポリシー名 (例: `accessPolicies/123456789012`) を設定します。

1. **Terraformの適用:**
   `bash scripts/sync-config.sh` を実行後、`terraform apply` を実行します。`bootstrap-deploy.sh`の対話形式でも設定可能です。

### 5.3 運用上の注意と必須権限

- **デフォルトは無効:** `enable_vpc_sc` はデフォルトで `false` のため、既存環境への影響はありません。
- **必須権限:** VPC-SCは組織リソースのため、Terraform実行主体には**組織レベル**で以下のIAMロールが**両方とも必要**です。権限がない場合、`terraform apply`は失敗します。対話形式のデプロイスクリプト `scripts/bootstrap-deploy.sh` は、VPC-SC有効化の際にこの権限付与を支援します。
  - **Access Context Manager 管理者 (`roles/accesscontextmanager.policyAdmin`)**
  - **組織管理者 (`roles/resourcemanager.organizationAdmin`)**

**VPC-SCとGoogle Apps Script (GAS) の致命的な相性に関する重要事項:**
もし `enable_vpc_sc` フラグを `true` にしてVPC-SCを有効化した場合、システムの心臓部であるGoogle Apps Script (GAS) からCloud RunのバックエンドAPI (`/api/requests`, `/execute` 等) へのOIDC通信は、VPC-SCの境界に弾かれて完全に遮断（403エラー）されます。
これは、GASがGoogleのパブリックな汎用サーバー（動的IP）上で動作しており、VPC-SCの「境界の外側」からのアクセスと見なされるためです。これを解決するには、GAS側に自力でOIDCトークンを生成させる複雑な改修が必要となり、「OIDCによるシンプルな連携」という現在のMVPの良さが失われてしまいます。
そのため、今回は\*\*「いつでもVPC-SCを有効化できるコード（スイッチ）は用意しておくが、GASの連携方式を根本から見直すまではフラグを `false` のまま運用する」\*\*という方針にご注意ください。

## 6. tfstateバックエンドのブートストラップ手順

**前提:**

- `saas.env` に `TFSTATE_BUCKET`, `TFSTATE_PREFIX`, `TFSTATE_LOCATION` を設定済み
- `saas.env` に `GAS_TRIGGER_OWNER_EMAIL` を設定済み

**実行:**

```bash
bash scripts/bootstrap-tfstate.sh
bash scripts/sync-config.sh
cd terraform
terraform init -backend-config=../backend.hcl
```

**確認:**

```bash
gcloud storage buckets describe gs://$(grep '^TFSTATE_BUCKET=' saas.env | cut -d= -f2)
```

### 6.1 オブジェクトのバージョニング有効化の推奨

Terraform Stateファイルを保存するGCSバケット (`${TFSTATE_BUCKET}` に設定されているバケット) については、**オブジェクトのバージョニング機能を必ず有効化**することを強く推奨します。

運用中に誤ってStateファイルが破損したり上書きされたりした場合、バージョニングが有効になっていないと、以前の管理状態への復旧が極めて困難になります。これは、インフラストラクチャの安定運用において非常に重要です。

**GCP Console または `gsutil` コマンドでの有効化例:**

```bash
gsutil versioning set on gs://${TFSTATE_BUCKET}
```

## 7. サービスアカウント作成コマンド（手動ブートストラップが必要な場合）

通常は Terraform が作成します (`google_service_account.executor` in `terraform/main.tf`)。

手動で先に作成する場合:

```bash
TOOL_PROJECT_ID="$(grep '^TOOL_PROJECT_ID=' saas.env | cut -d= -f2)"

gcloud iam service-accounts create iam-access-executor
  --project "$TOOL_PROJECT_ID"
  --display-name "IAM Access Executor"
```

## 8. コマンド付き運用手順書

**最短導線（対話形式）:**

```bash
bash scripts/bootstrap-deploy.sh
```

### 8.1 初回セットアップ

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

### 8.2 反映後の設定

```bash
cd terraform
terraform output cloud_run_url
```

- 出力値を `apps-script/script-properties.json` の `CLOUD_RUN_EXECUTE_URL` に反映します。

### 8.3 SQL適用（帳票準拠）

```bash
# BigQuery UI か bq query で以下のSQLを順番に実行してください
# 1. build/sql/001_tables.sql (コアテーブル)
# 2. build/sql/004_workbook_tables.sql (ワークブックマスタ)
# 3. build/sql/002_views.sql (コアビュー)
# 4. build/sql/005_workbook_views.sql (シート互換ビュー)
# 5. build/sql/007_seed_workbook_from_existing.sql (初期データシード)
```

### 8.4 変更リリース（通常運用）

```bash
bash scripts/sync-config.sh
cd terraform
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

### 8.5 収集ジョブ手動実行（フォルダ/プロジェクト・Googleグループ）

```bash
cd terraform
CLOUD_RUN_URL="$(terraform output -raw cloud_run_url)"

bash ../scripts/collect-resource-inventory.sh --cloud-run-url "$CLOUD_RUN_URL"
bash ../scripts/collect-google-groups.sh --cloud-run-url "$CLOUD_RUN_URL"
```

### 8.6 Cloud Scheduler（日次自動実行）確認

```bash
cd terraform
terraform output resource_inventory_scheduler_job
terraform output group_collection_scheduler_job
gcloud scheduler jobs describe iam-resource-inventory-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-group-collection-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-reconciliation-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-revoke-expired-permissions-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
gcloud scheduler jobs describe iam-bindings-history-update-daily --location "$(grep '^REGION=' ../saas.env | cut -d= -f2)" --project "$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2)"
```

### 8.7 障害時の一次切り分け

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
 FROM `$(grep '^TOOL_PROJECT_ID=' ../saas.env | cut -d= -f2).$(grep '^BQ_DATASET_ID=' ../saas.env | cut -d= -f2).iam_pipeline_job_reports`
 ORDER BY occurred_at DESC LIMIT 50"
```

## 9. リソースの削除保護

本システムのTerraform構成では、データの永続性と監査証跡の完全性を保証するため、特に重要なリソースに対して削除保護が設定されています。

### 9.1 BigQuery監査テーブルの保護

- **対象リソース:** 申請履歴 (`iam_access_requests`) や実行ログ (`iam_access_change_log`) など、監査証跡として機能するすべてのBigQueryテーブル。
- **保護の仕組み:** Terraformリソースに `lifecycle { prevent_destroy = true }` が設定されています。
- **影響:** この設定により、`terraform destroy` コマンドを実行しても、これらのテーブルは**削除されません**。Terraformは削除操作の前にエラーを発生させて停止します。
- **目的:** 誤操作による監査データの完全な喪失を防ぐことが目的です。

#### テーブルを意図的に削除する場合

万が一、これらのテーブルを意図的に削除する必要が生じた場合（例: プロジェクト全体の廃止時）、以下の手順を踏む必要があります。

1. **Terraformコードの変更:**
   `terraform/modules/bigquery/main.tf` を開き、対象となる `google_bigquery_table` リソースから `lifecycle { prevent_destroy = true }` ブロックをコメントアウトまたは削除します。
1. **Terraformの適用:**
   変更を適用します (`terraform apply`)。
1. **Terraformによる削除:**
   `terraform destroy` を再度実行すると、保護が解除されたテーブルが削除されます。

この操作は、監査データが不要であることを完全に確認してから、慎重に行ってください。

## 10. 未テスト項目の申し送り運用

- 未テスト事項は `docs/untested-items-handover.md` に記録して管理します。
- 新機能や権限変更を入れた場合は、同ファイルへ項目追加してからリリースします。
- 検証が完了したら、状態を更新して証跡（クエリ結果/ログ）を紐づけます。
