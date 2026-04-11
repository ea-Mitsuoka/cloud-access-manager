# Scripts

このディレクトリには、Cloud Access Managerのデプロイ、破棄、およびデータ収集などの各種運用を自動化するためのシェルスクリプトが含まれています。

## デプロイと破棄のアーキテクチャ (State分離運用)

本システムでは、Terraformの運用を安全に行うため、リソースを「ステートフル（恒久データ）」と「ステートレス（再作成可能）」に厳格に分離し、スクリプト側で `terraform state rm` と `import` を駆使してライフサイクルをコントロールしています。

### ⚠️ 特殊なリソース管理: `iam_policy_permissions` テーブル

BigQueryモジュール（`terraform/modules/bigquery/main.tf`）内で作成されるリソースのうち、**`iam_policy_permissions` テーブルのみ、例外的に「ステートレス（いつでも破棄・再作成可能）」なリソースとして扱っています。**

- **理由:**
  このテーブルは、日次のジョブによって定期的に洗い替えされる「インベントリ（スナップショット）データ」です。監査ログのように過去の履歴を永続化する必要がないため、Terraformのスキーマ変更があった際に、差分エラーで止まることなく安全かつクリーンに再作成（スクラップ＆ビルド）させることを意図しています。

- **スクリプトにおける実装の詳細:**
  この要件を満たすため、各スクリプト・コードにおいて以下の特殊なハンドリングを行っています。

  1. **`teardown.sh` (破棄時):**
     BigQueryリソースを保護（`state rm`）する処理において、`grep -v "iam_policy_permissions"` を用いてこのテーブルだけを保護対象から除外しています。これにより、`destroy` 実行時にGCP上から完全に削除されます。
  1. **`bootstrap-deploy.sh` (構築時):**
     デプロイ前の `terraform import` リストから意図的に除外しています。これにより、再構築時にTerraformが「存在しない」と正しく認識し、まっさらな状態で新規作成します。
  1. **Terraformコード (`main.tf`):**
     このテーブルのみ、GCPのAPIブロックを回避するために明示的に `deletion_protection = false` を設定しています。

## 主要なスクリプト一覧

| スクリプト名 | 役割 |
| :--- | :--- |
| `bootstrap-deploy.sh` | 初期設定の同期、Dockerイメージのビルド、既存監査データのImport、およびTerraform Applyを全自動で行うデプロイパイプラインです。 |
| `onboard-tenant.sh` | インフラデプロイ完了後、テナント側での権限付与が終わったタイミングで実行し、初期データの収集と帳票のセットアップ（Seed）を行います。 |
| `teardown.sh` | 監査ログ（BigQuery）や基本APIの設定をStateから安全に退避させた上で、Cloud RunやSchedulerなどのコンピュートリソースのみを綺麗に削除します。 |
| `sync-config.sh` | `saas.env` に設定された環境変数を読み込み、TerraformやCloud Run、GAS向けの各設定ファイル（`.tfvars`, `.env`, `json`）を自動生成します。 |
| `collect-*.sh` | 手動でデータ収集ジョブ（Cloud Runエンドポイント）をキックするためのユーティリティです。 |
