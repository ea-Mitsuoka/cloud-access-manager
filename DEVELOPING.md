# ローカル開発・引き継ぎガイド

本ドキュメントは、Cloud Access Manager の開発環境のセットアップ、テスト、およびコントリビューションのワークフローを新規参画者（開発者・SRE）へ引き継ぐためのガイドです。

## 1. プロジェクトの全体像とディレクトリ構成

本リポジトリは、複数の技術スタックで構成されています。開発を行う際は、対象となるコンポーネントのディレクトリで作業を行います。

- **`cloud-run/`**: 実行エンジン（Python / Flask / Poetry）。IAMの実行やデータ収集バッチを担います。本ガイドの主な対象です。
- **`terraform/`**: インフラストラクチャ定義（HCL）。GCPリソースのプロビジョニングを行います。
- **`apps-script/`**: 申請UIと承認フロー（JavaScript / GAS）。Googleフォームおよびスプレッドシートと連携します。
- **`sql/`**: BigQueryのテーブル・ビュー定義（SQL）。

## 2. 前提条件 (Prerequisites)

開発を始める前に、ローカルマシンに以下のツールがインストールされていることを確認してください。

- **Python**: 3.12 (`cloud-run/pyproject.toml` に準拠)
- **Poetry**: Pythonの依存関係管理およびパッケージングツール
- **gcloud CLI**: Google Cloud との認証・操作用 (`gcloud auth login` 実施済みであること)
- **Terraform**: 1.6+ (インフラ変更時のみ)
- **Docker**: コンテナイメージのローカルビルド用 (オプション)

## 3. 初回セットアップ (First-time Setup)

リポジトリをクローンした直後に、以下の手順でローカル環境を構築します。

### 3.1. 環境変数の構成

ルートディレクトリに設定ファイルを作成し、開発用のGCPプロジェクト情報を入力します。

```bash
cp saas.env.example saas.env
# vi saas.env を開き、TOOL_PROJECT_ID や BQ_DATASET_ID 等を設定
# その後、同期スクリプトを実行して各コンポーネント（Terraform, Python, GAS）へ設定を分配します。
bash scripts/sync-config.sh
```

※これにより cloud-run/.env などが自動生成されます。

### 3.2. Python環境の構築 (Poetry)

バックエンドAPIの開発環境をセットアップします。

```bash
cd cloud-run
poetry install
```

## 4. 開発とテスト (Development & Testing)

バックエンド（`cloud-run/`）のコードを変更した際は、コミット前に必ず静的解析とテストを実行してください。

### 4.1. 静的解析 (Linting)

コードがスタイルガイドラインに準拠しているか確認します。

```bash
# cloud-run ディレクトリで実行
poetry run flake8 --config=.flake8 app/
```

### 4.2. 単体・シナリオテスト (pytest)

テストスイートを実行し、既存機能のデグレードがないか確認します。

> **💡 テストのGCP依存について（完全モック化）**
> 本プロジェクトのテストコードは `unittest.mock` を用いてGCP API（BigQuery, IAM, Cloud Asset等）や認証情報を完全にモック化しています。そのため、GCPのサービスアカウント鍵やネットワーク接続がなくても、ローカル環境で安全かつ高速にテストを実行可能です。

```bash
# 1. コードのフォーマットを統一
poetry run black app
# 2. 静的解析（構文チェック）を実行
poetry run flake8
# 3. テストの実行（モックアーキテクチャによりGCP環境不要で完結します）
poetry run pytest
```

テストには以下が含まれます:

- 実行フローテスト: 権限付与/剥奪のビジネスロジック (test_main_execute_flow.py)
- コレクターフローテスト: 収集パイプラインの挙動 (test_collectors_flow.py)
- バッチ・APIテスト: 定期ジョブやWeb APIの挙動 (test_jobs.py, test_api.py)

## 5. ローカルサーバーでの動作確認

Flaskアプリケーションをローカルで起動し、基本的なヘルスチェック等を行うことができます。
(※実際のAPI実行にはGCP認証が必要なため、フルテストは単体テストで行うか、開発用GCP環境へデプロイして確認してください)

```bash
cd cloud-run
poetry run flask --app app/main run
```

別のターミナルから以下を実行し、{"ok":true} が返れば正常に稼働しています。

```bash
curl [http://127.0.0.1:5000/healthz](http://127.0.0.1:5000/healthz)
```

## 6. コントリビューション・フロー (CI/CD)

本リポジトリは GitHub Actions (`.github/workflows/ci.yml`) を利用してCI/CDを自動化しています。

1. **ブランチ作成**: `main` から作業ブランチを切ります。
1. **ローカル検証**: コード変更後、上記の `flake8` と `pytest` をローカルでパスさせます。
1. **Pull Request作成**: PRを作成すると、CIでLintとTest、およびTerraformのセキュリティスキャン(`tfsec`)と `terraform plan` が自動実行されます。
1. **マージと自動デプロイ**: レビュー後に `main` ブランチへマージすると、本番環境の Cloud Run および Terraform リソースへ自動デプロイされます。シークレットキーの管理にはセキュアな Workload Identity Federation (WIF) を利用しています。

## 7. ドキュメントのプレビュー (MkDocs)

本プロジェクトは MkDocs を使用して統合ドキュメントとPython APIリファレンスを生成しています。ドキュメント (`docs/` 配下) を編集した際は、ローカルで表示を確認できます。

```bash
cd cloud-run
poetry run mkdocs serve -f ../mkdocs.yml
```

ブラウザで`http://127.0.0.1:8000`にアクセスしてください。

## 8. ドキュメントマップ（次に読むべきファイル）

システムの理解を深めるため、目的・役割に応じて以下のドキュメントを参照してください。

| ドキュメントファイル | 役割と目的 | ユースケース |
| :--- | :--- | :--- |
| **`README.md`** | プロジェクトの顔（ポータル） | 全体アーキテクチャや主要機能の把握、各種ドキュメントへの玄関口として利用。 |
| **`docs/design/requirements.md`** | 要件定義書 | なぜこのシステム構成になったか（非機能要件や制約）を理解する際に参照。 |
| **`docs/operation/operations-runbook.md`** | SRE向け運用手順書 | デプロイ手順、コスト管理、VPC-SC設定、トラブルシューティングを行う際に参照。 |
| **`docs/operation/iam-reconciliation-and-incident-flow.md`** | インシデント対応と監査 | 野良権限検知時の対応や、BigQueryを用いた監査用SQLを調べる際に参照。 |
| **`docs/design/data_lineage_and_mapping.md`** | データリネージ | スキーマ変更時や、APIから帳票(スプレッドシート)までのデータの流れを追う際に参照。 |
| **`docs/design/bigquery_tables.md`** | テーブル仕様書 | 全13テーブルの用途や更新方式を正確に把握する際に参照。 |
| **`docs/development/untested-items-handover.md`** | QA・未テスト台帳 | リリース前に消化すべきテスト項目や、過去の検証履歴を確認する際に参照。 |
| **`CHANGELOG_SUMMARY.md`** | 変更履歴 | 過去の開発の文脈や、バグ修正の経緯をビジネス視点で確認する際に参照。 |
