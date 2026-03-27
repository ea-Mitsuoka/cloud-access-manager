# ローカル開発ガイド (Poetry)

このガイドでは、Poetry を使用してローカル開発環境をセットアップするための手順を説明します。これらの手順に従うことで、単体テストを実行し、変更をコミットする前に検証することができます。

## 1. 前提条件

始める前に、ローカルマシンに以下のツールがインストールされ、設定されていることを確認してください。

- **Poetry**: Python の依存関係管理およびパッケージングツール。
- **gcloud CLI**: Google Cloud のコマンドラインツール。
- **Terraform**: Infrastructure as Code ツール。
- **Python**: バージョン 3.12 (プロジェクトの `pyproject.toml` で指定)。
- **Docker**: コンテナイメージをビルドするため（ローカルテストではオプション）。

また、開発およびテスト用の Google Cloud プロジェクトへのアクセス権があり、`gcloud` CLI が認証済みである必要があります (`gcloud auth login`)。

## 2. 設定

1. **`saas.env` ファイルの作成**:
   リポジトリのルートに `saas.env` ファイルがない場合は、サンプルファイルをコピーして作成します。

   ```bash
   cp saas.env.example saas.env
   ```

1. **`saas.env` の編集**:
   `saas.env` を開き、ローカルセットアップに必要な値を入力します。主に以下の項目です。

   - `TOOL_PROJECT_ID`: 開発用の Google Cloud プロジェクトID。
   - `REGION`: リソースの GCP リージョン。
   - `BQ_DATASET_ID`: テスト用の BigQuery データセットID (例: `iam_access_mgmt_dev`)。

## 3. 環境のセットアップとテスト

Poetry は環境のセットアップとコマンドの実行を簡素化します。

1. **`cloud-run` ディレクトリへの移動**:
   Python プロジェクトはこのディレクトリで定義されています。

   ```bash
   cd cloud-run
   ```

1. **依存関係のインストール**:
   このコマンドは、ディレクトリ内に新しい仮想環境を作成し、`pyproject.toml` で指定されたすべてのアプリケーションおよび開発依存関係をインストールします。

   ```bash
   poetry install
   ```

1. **単体テストの実行**:
   テストスイートを実行するには、プロジェクトの仮想環境内でコマンドを実行する `poetry run` を使用します。

   ```bash
   poetry run pytest
   ```

   このコマンドは `app/tests/` ディレクトリ内のすべてのテストを検出し、実行します。

## 4. アプリケーションのローカル実行 (基本的なチェック)

基本的なチェックのために、Flask アプリケーションをローカルで実行できます。

**重要な注意**: ほとんどのエンドポイントは、実際の Google Cloud 認証と権限を必要とします。ローカルでの実行は、エンドツーエンドのテストのために開発環境にデプロイする代わりには**なりません**。

1. **`cloud-run` ディレクトリへの移動** (まだ移動していない場合)。

1. **環境変数の設定**:
   アプリケーションは `saas.env` の環境変数に依存しています。まず、**リポジトリのルート**から同期スクリプトを実行して、`.env` ファイルが最新であることを確認します。

   ```bash
   # From the repository root
   bash scripts/sync-config.sh
   ```

   Poetry は `pyproject.toml` と同じディレクトリに `.env` ファイルが存在する場合、自動的に変数を読み込むことができます。`sync-config.sh` スクリプトはすでに `cloud-run/.env` を作成しているため、手動での `export` は不要です。

1. **Flask アプリの実行**:
   `poetry run` を使用して、管理された環境内で Flask を実行します。

   ```bash
   # From the ./cloud-run directory
   poetry run flask --app app/main run
   ```

1. **ヘルスチェックのテスト**:
   新しいターミナルで、ヘルスチェックエンドポイントにアクセスできます。

   ```bash
   curl http://127.0.0.1:5000/healthz
   ```

   `{"ok":true}` というレスポンスが表示されるはずです。
