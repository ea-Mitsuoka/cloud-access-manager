# IAMロール名日本語化アーキテクチャ設計書

## 1. 概要・アプローチ

現在、GAS内でハードコードして処理している「IAMロール名の日本語化（表示名変換）」を、エンタープライズ・アーキテクチャのベストプラクティスに従い、BigQuery上のマスタテーブルを用いたデータモデリング（スタースキーマ構成）へ移行する。
これにより、「コードの肥大化」や「他ツールとの非互換性」といった技術的負債を回避し、Terraform（IaC）によるシステム全体の一貫性を確保する。

## 2. 本設計の優位性（3つの理由）

1. **Single Source of Truth（信頼できる唯一の情報源）の確立**
   BigQuery上にマスタテーブルを持つことで、GAS（スプレッドシート）だけでなく、将来 Looker Studio や Tableau などのBIツールを繋いだときにも、全く同じ日本語のロール名を共通して利用できる。
1. **メンテナンスの分離**
   新しいロールの日本語訳を追加する際、GASのプログラム（ソースコード）を変更・デプロイする必要がなく、BigQueryのマスタテーブルの該当行を更新するだけでシステム全体に即時反映される。
1. **既存の安全性（トランザクションの保護）**
   日々の申請や付与・剥奪を記録している巨大な履歴テーブル（トランザクション）には一切手を加えないため、システムの根幹が壊れるリスクがない。ビュー（SQL）の `LEFT JOIN` を追加するだけの極めて安全でスマートな拡張である。

______________________________________________________________________

## 3. 実装ロードマップ（Terraform構成案）

手動操作を排除し、Terraformに「ロールの自動収集」と「日本語名のマスタ管理」を組み込む。

### ① マスタテーブルの定義 (`iam_role_master`)

ロールIDと日本語名を保持するネイティブテーブルを作成する。

```hcl
# IAMロール日本語名称マスタ
resource "google_bigquery_table" "iam_role_master" {
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "iam_role_master"
  project    = var.project_id

  schema = <<SCHEMA
[
  {"name": "role_id", "type": "STRING", "mode": "REQUIRED", "description": "正式なロールID (例: roles/storage.admin)"},
  {"name": "role_name_ja", "type": "STRING", "mode": "NULLABLE", "description": "日本語表示名"}
]
SCHEMA

  # 削除保護（運用データのため）
  deletion_protection = false
}
```

### ② 週次自動更新（ロール自動検出）の設定

Scheduled Query を用い、環境内で新しく使われ始めたロールを毎週自動検出し、マスタに「未翻訳」として追記する。

```hcl
# 週次で新しいロールをマスタに自動追加するジョブ
resource "google_bigquery_data_transfer_config" "weekly_role_sync" {
  display_name           = "Weekly IAM Role Discovery"
  data_source_id         = "scheduled_query"
  schedule               = "every monday 09:00"
  destination_dataset_id = google_bigquery_dataset.main.dataset_id
  project                = var.project_id

  params = {
    query = <<QUERY
      # 実際に検知されている権限リストから、マスタに存在しないロールを抽出して追加
      INSERT INTO `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_role_master` (role_id)
      SELECT DISTINCT role
      FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_policy_permissions`
      WHERE role NOT IN (SELECT role_id FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_role_master`)
    QUERY
  }
}
```

### ③ 既存ビュー (`v_sheet_iam_permission_history`) の修正

元の英名列（`role`）は監査・システム要件のためにそのまま残し、マスタを `LEFT JOIN` して新しい表示用の列（`role_display_name`）を追加する。

```hcl
# ビューの再定義 (マスタをJOIN)
resource "google_bigquery_table" "v_sheet_iam_permission_history" {
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "v_sheet_iam_permission_history"
  project    = var.project_id

  view {
    query = <<QUERY
      SELECT
        h.*,
        # マスタに日本語名があれば採用、なければ 'roles/' を抜いた英名を表示用ロール名とする
        COALESCE(m.role_name_ja, REGEXP_REPLACE(h.role, r'^roles/', '')) AS role_display_name
      FROM
        `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_permission_bindings_history` AS h
      LEFT JOIN
        `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_role_master` AS m
      ON
        h.role = m.role_id
      WHERE
        snapshot_date = (SELECT MAX(snapshot_date) FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.iam_permission_bindings_history`)
    QUERY
    use_legacy_sql = false
```
