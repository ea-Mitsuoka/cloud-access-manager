# Cloud Run: IAM Access Executor

このディレクトリには、Python/Flaskアプリケーションが含まれており、IAMアクセス管理システムの実行エンジンとして機能します。

このアプリケーションは、コンテナイメージにビルドされ、リポジトリのルートにあるTerraform設定を介してCloud Runサービスとしてデプロイされるように設計されています。

## 主要な機能 (Core Functions)

- **IAMリクエストの実行**: 承認済みの権限付与・剥奪リクエストをIAM API経由で実行します。
- **データ収集ジョブ**: Cloud Schedulerからトリガーされ、GCPリソースやGoogleグループの情報を収集します。
- **不整合検知と履歴作成**: 定期的に権限の不整合を検知し、棚卸し用の履歴データを作成します。

## エンドポイント (Endpoints)

- `GET /healthz`: ヘルスチェック用エンドポイント。
- `POST /execute`: 指定された `request_id` に基づき、権限の付与・剥奪を実行します。
- `POST /collect/resources`: GCPリソース（プロジェクト、フォルダ）のインベントリを収集します。
- `POST /collect/principals`: Google Workspace（User/Group）とGCP IAM（Service Account）からプリンシパル情報を収集し、Googleグループのメンバーシップ履歴も更新します。
- `POST /reconcile`: 申請内容と実際の権限の不整合を検知します。
- `POST /revoke_expired_permissions`: 期限切れの権限を自動的に剥奪します。
- `POST /jobs/update-iam-bindings-history`: 帳票用の整形済み権限履歴テーブルを更新します。

## 環境変数 (Environment Variables)

このCloud Runサービスに必要なすべての環境変数は、Terraformによってインフラ定義 (`terraform/main.tf`) の中で設定されます。

設定値のマスターソースは、リポジトリのルートにある `saas.env` ファイルです。このファイルの値が `scripts/sync-config.sh` を通じてTerraformに渡されます。詳細については、ルートの `README.md` および `DEVELOPING.md` を参照してください。

## デプロイ (Deployment)

**このサービスを `gcloud run deploy` コマンドで手動デプロイすることは推奨されません。**

デプロイは、リポジトリルートのTerraform定義とCI/CDパイプライン（GitHub Actions）によって一元管理されます。

1. **コンテナイメージのビルド**: `Dockerfile` はPoetryを使用したマルチステージビルドになっており、CI/CDパイプラインで自動的にビルドされ、Artifact Registryにプッシュされます。
1. **Cloud Runサービスの定義**: `terraform/main.tf` 内の `google_cloud_run_v2_service` リソースが、使用するコンテナイメージ、サービスアカウント、環境変数、Ingress設定などをすべて定義します。
1. **適用**: `terraform apply` を実行すると、定義に基づいたCloud Runサービスが作成・更新されます。

詳細なデプロイ手順については、リポジトリルートの `README.md` および `docs/operations-runbook.md` を確認してください。
