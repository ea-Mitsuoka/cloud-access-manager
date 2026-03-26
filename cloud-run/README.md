# Cloud Run Executor

このサービスは、承認されたIAMリクエストを実行し、すべての実行をBigQueryに記録します。

## エンドポイント

- `GET /healthz`
- `POST /execute` ペイロード: `{ "request_id": "..." }`
- `POST /collect/resources` (フォルダ/プロジェクトのインベントリをBigQueryの履歴に収集)
- `POST /collect/groups` (GoogleグループとメンバーシップをBigQueryに収集)

## 環境変数

- `BQ_PROJECT_ID` (必須)
- `BQ_DATASET_ID` (必須)
- `MGMT_TARGET_PROJECT_ID` (プロジェクト単体モードで必須)
- `MGMT_TARGET_ORGANIZATION_ID` (オプション; 設定されている場合、プロジェクトの祖先がこの組織に対して検証されます)
- `WORKSPACE_CUSTOMER_ID` (オプション, デフォルト: `my_customer`)
- `EXECUTOR_IDENTITY` (オプション)
- `WEBHOOK_SHARED_SECRET` (Terraformのデプロイ時にSecret Managerから読み込まれます)

## デプロイ例

```bash
gcloud run deploy iam-access-executor 
  --source cloud-run 
  --region asia-northeast1 
  --service-account iam-executor@YOUR_PROJECT.iam.gserviceaccount.com 
  --set-env-vars BQ_PROJECT_ID=YOUR_PROJECT,BQ_DATASET_ID=YOUR_DATASET 
  --allow-unauthenticated
```

ネットワークレベルの制御（IAP/VPC-SCまたはイングレス制限）と、Secret Managerをバックエンドとする`WEBHOOK_SHARED_SECRET`を使用してください。

## リソースインベントリ収集

webhookトークンヘッダーを付けて `/collect/resources` を呼び出します。

```bash
curl -X POST "https://<service-url>/collect/resources" 
  -H "Content-Type: application/json" 
  -H "X-Webhook-Token: <token>" 
  -d '{}'
```

定期的な実行のために、TerraformはOIDCを使用してこのエンドポイントを毎日呼び出すCloud Schedulerをプロビジョニングします。
権限エラーは、実行可能な`hint`とともに`FAILED_PERMISSION`として返され、BigQueryの`pipeline_job_reports`にも記録されます。

## Googleグループ収集

webhookトークンヘッダーを付けて `/collect/groups` を呼び出します。

```bash
curl -X POST "https://<service-url>/collect/groups" 
  -H "Content-Type: application/json" 
  -H "X-Webhook-Token: <token>" 
  -d '{}'
```

注意：

- グループ収集はCloud Identity APIを使用し、GCP IAMに加えてWorkspace側の読み取り権限が必要です。
- 権限エラーは、実行可能な`hint`とともに`FAILED_PERMISSION`として返され、BigQueryの`pipeline_job_reports`にも記録されます。
