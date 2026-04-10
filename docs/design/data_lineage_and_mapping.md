# Cloud Access Manager データリネージとマッピング定義

本ドキュメントは、Cloud Access Managerにおける全13テーブル・全カラムの因果関係（データリネージ）を定義したものです。
情報の発生源である **GCP API** や **SaaSポータル（WebアプリUI）** から、加工・保存を担う **GAS/Python**、そして最終的な監査要件である **スプレッドシート帳票** に至るまでのデータの血統を網羅しています。

システムの改修やトラブルシューティング時において、上流と下流の不一致がないかを精査するためのマスターデータとして活用してください。

______________________________________________________________________

## 1. システム全体の因果関係とデータフロー

情報の流れは大きく「実態の収集フロー（API → BigQuery → 帳票）」と、「申請・実行フロー（UI → GAS → Cloud Run → API）」の2軸で構成されています。

### 1.1 上流（データの源泉と収集）: GCP API → Python

- **Google Cloud Asset API (`search_all_iam_policies`)**
  - **仕様/役割:** GCP環境の「実際のIAMバインディング（誰が・どの権限を持っているか）」を取得します。
  - **取得データ:** `resource` (例: `//cloudresourcemanager.googleapis.com/projects/my-project`), `policy.bindings.role`, `policy.bindings.members`。
- **Python (`iam_policy_collector.py`)**
  - **役割 (Extract):** APIのレスポンスをフラットな辞書型に変換します。
  - **マッピング:** `resource` は先頭のプレフィックスをパースせずそのまま `resource_name` にマッピングします。`members` (例: `user:foo@example.com`) は `:` で分割し、`principal_type` と `principal_email` に分解します。

### 1.2 中流（インフラと保存）: Terraform → DDL → BigQuery

- **デプロイ環境設定 (`saas.env` -> `environment.auto.tfvars`)**
  - **役割:** 収集スコープやバッチの実行スケジュール、BQデータセット名 (`BQ_DATASET_ID`) を定義し、システム全体の振る舞いを決定します。
- **Terraform (`terraform/modules/bigquery/main.tf`)**
  - **役割 (Infrastructure):** BigQueryのコアテーブルの物理スキーマを定義します。
  - **マッピング:** Pythonから送られてくる実態データを保存する `iam_policy_permissions` テーブルを定義します（列: `resource_name`, `principal_type`, `principal_email`, `role` など）。

### 1.3 下流（加工と監査）: Python → SQL Views → 監視

- **Python (`repository.py` の `run_update_bindings_history_job`)**
  - **役割 (Transform):** 「GCPの現実（`iam_policy_permissions`）」と「過去の申請履歴（`iam_access_requests`）」を JOIN します。
  - **マッピング:** 現実のバインディング情報に、申請時の `ticket_ref` や `reason` (申請理由)、`approver_email` (承認者) の文脈を付与して `iam_permission_bindings_history` に書き込みます。
- **SQL Views (`sql/005_workbook_views.sql`)**
  - **役割:** データベースの物理カラム名を、スプレッドシート（UI）で表示するための日本語カラム名に変換する「最終出力アダプター」です。
  - **マッピング:** `resource_name` -> `リソース名`、`principal_email` -> `プリンシパル`、`iam_role` -> `IAMロール`。

### 1.4 フロントエンド（意図の入力と反映）: UI → GAS → Cloud Run

- **ビジネス要件 (Web App & Sheets)**
  - **役割:** ユーザーがAI推論アシスタントを利用しながら権限を要求し、管理者が承認・棚卸しを行うインターフェース。
  - **要求される項目:** `対象プリンシパル`, `対象リソース`, `付与・変更ロール`, `申請理由・利用目的`, `利用期限`, `承認者メール`。
- **GAS (`Code.gs` & `RoleAdvisor.html`)**
  - **役割:** Webアプリのフォーム入力をAIを用いてリアルタイム検証（タイポ検知等）した上で抽出し、システムが解釈できる英語キーのJSONペイロードにマッピングします。
  - **マッピング:** `formData.resource` -> `resource_name`、`formData.reason` -> `reason` 等。これを Cloud Run の `/api/requests` へ送信します。

______________________________________________________________________

## 2. コア情報のデータマッピング・マトリクス

最も重要かつ不整合が起きやすい「アクセス権のコア情報（誰が・何に・何の権限を）」が、各レイヤーでどう命名され引き継がれているかの一覧です。

| 概念 | ① GCP API (現実) | ② Webポータル/GAS (意図) | ③ Python/BQ (正本) | ④ 履歴結合 (SQL) | ⑤ スプレッドシート (UI) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **リソース** | `resource` | `対象リソース` | `resource_name` | `resource_name` | `リソース名` |
| **対象者** | `members`内の値 | `対象プリンシパル` | `principal_email` | `principal_email` | `プリンシパル` |
| **対象者の型**| `members`の接頭辞 | (入力なし/自動判定) | `principal_type` | `principal_type` | `種別` |
| **ロール** | `role` | `付与・変更ロール` | `role` | `iam_role` | `IAMロール` |
| **理由** | (GCPには存在しない) | `申請理由・利用目的` | `reason` | `request_reason` | `申請理由・用途` |
| **ステータス**| (GCPには存在しない) | `承認済` / `申請中` | `status` (PENDING等) | `status_ja` | `ステータス` |

______________________________________________________________________

## 3. 全13テーブルのデータリネージ詳細

### 3.1 申請・承認・実行フロー系テーブル

#### `iam_access_requests` (申請の正本)

ユーザーの申請内容と、現在のステータスを管理します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `request_group_id` | Webポータル / GAS内部生成 | 一括申請単位でUUIDを採番し、各明細に付与 | 一括申請の監査トレース、レビュー時のグルーピング |
| `request_id` | GAS内部生成 | `Utilities.getUuid()` で生成 | 全テーブルの結合キー、`/execute` APIの引数 |
| `request_type` | ポータル「申請種別」 | GASで `GRANT/REVOKE/CHANGE` に正規化 | 実行エンジンのアクション判定 (`_normalize_action`) |
| `principal_email` | ポータル「対象プリンシパル」 | GASからそのまま送信 | IAM付与対象、履歴および不整合検知の結合キー |
| `resource_name` | ポータル「対象リソース」 | GASの `normalizeResourceName_` で `projects/` などを補完 | IAM付与対象、履歴および不整合検知の結合キー |
| `role` | ポータル「付与・変更ロール」| GAS（およびAI）で検証後、そのまま送信 | IAM付与対象、履歴および不整合検知の結合キー |
| `reason` | ポータル「申請理由」 | 緊急時はプレフィックス `[緊急]` を付与 | 履歴スナップショット、監査時のレビュー根拠 |
| `expires_at` | ポータル「利用期限」 | GASでパースし、指定日の `23:59:59.999` に変換 | 自動剥奪バッチ (`/revoke_expired_permissions`) の対象判定 |
| `requester_email` | ポータル自動取得 | ログイン中のアカウントメールアドレスを取得 | 申請履歴イベントの記録 |
| `approver_email` | ポータル「承認者」 | GASからそのまま送信 | 申請履歴イベントの記録 |
| `status` | GAS / スプレッドシート | 初期は `PENDING`。GAS経由やPythonバッチで更新 | 実行可否判定 (`APPROVED` のみ実行) |
| `requested_at` | GAS実行日時 | GASの `new Date().toISOString()` | 帳票表示、時系列ソート |
| `approved_at` | Python実行日時 | ステータスが `APPROVED` に更新された際に記録 | 帳票表示、監査レビュー |
| `ticket_ref` | (未使用枠) | GASで空文字をセット | 帳票表示（社内チケット番号用） |
| `created_at` | Python実行日時 | BQ挿入時の `CURRENT_TIMESTAMP()` | システム監査用 |
| `updated_at` | Python実行日時 | ステータス更新時等に `CURRENT_TIMESTAMP()` | システム監査用 |

#### `iam_access_change_log` (Cloud RunのAPI実行ログ)

Cloud Runが実際にGCPのIAM APIを叩いた結果を記録します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `execution_id` | Python内部生成 | `/execute` 呼び出し時に `uuid.uuid4()` で生成 | ログの一意識別 |
| `request_id` | `iam_access_requests` | 処理対象のリクエストIDを引き継ぐ | 帳票の「最新実行結果」取得時の結合キー |
| `action` | `iam_access_requests` | `request_type` から `GRANT/REVOKE` に変換 | 帳票表示、監査 |
| `target` | `iam_access_requests` | `resource_name` をそのまま引き継ぐ | 帳票表示、監査 |
| `before_hash` | Cloud Asset API | 変更前のIAMポリシーをSHA256ハッシュ化 | 変更有無の差分証明 |
| `after_hash` | Cloud Asset API | 変更後(setIamPolicy後)のポリシーをハッシュ化 | 変更有無の差分証明 |
| `result` | Python実行結果 | 処理結果に応じて `SUCCESS / FAILED / SKIPPED` をセット | スプレッドシートの「実行結果」列の同期元 |
| `error_code` | Python例外オブジェクト | 例外発生時に `type(exc).__name__` を取得 | エラーハンドリング・障害調査 |
| `error_message` | Python例外オブジェクト | 例外発生時に `str(exc)` を取得 | エラーハンドリング・障害調査 |
| `executed_by` | 環境変数設定 | `EXECUTOR_IDENTITY` (実行サービスアカウント) を取得 | 監査 |
| `executed_at` | Python実行日時 | API実行終了時に取得 | 時系列ソート、「最新実行結果」の判定用 |
| `details` | Python例外オブジェクト | トレースバック情報をJSONとして格納 | 障害時の詳細調査 |

#### `iam_access_request_history` (申請の変更履歴/監査ログ)

ステータス遷移と、その時点の理由などを不変のイベントとして記録します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `history_id` | GAS / Python内部生成 | 各処理で UUID を生成 | 履歴の一意識別 |
| `request_group_id` | `iam_access_requests` | 申請正本から引き継ぐ | 一括申請単位での監査・追跡 |
| `request_id` | `iam_access_requests` | 対象のIDを引き継ぐ | 申請ごとの履歴トレース |
| `event_type` | 処理のコンテキスト | 申請送信時は `REQUESTED`、以降は `STATUS_CHANGED` | 履歴のフィルタリング |
| `old_status` | 処理前のステータス | DBの現在ステータス、または空文字 | ステータス遷移の監査 |
| `new_status` | 処理後のステータス | 適用する新ステータス | ステータス遷移の監査 |
| `reason_snapshot` | `iam_access_requests` | その時点での `reason` (申請理由) をコピー | 後から改ざんできない監査証跡 |
| `request_type` ～ `approver_email` | `iam_access_requests` | その時点での申請内容全体をスナップショットとしてコピー | 変更履歴ビュー (`v_iam_request_approval_history`) |
| `acted_by` | 操作者のコンテキスト | GASの `Session.getActiveUser()` または `SYSTEM_AUTO_REVOKE` 等 | 誰が操作・承認したかの監査 |
| `actor_source` | 処理のコンテキスト | `WEB_APP_BULK`, `SHEET_BULK_REVIEW`, `SYSTEM_BATCH` 等 | どこから操作されたかの監査 |
| `event_at` | 処理日時 | 処理実行時のタイムスタンプ | 時系列ソート |
| `details` | 処理のコンテキスト | Webからの送信や一括更新のメタデータをJSONで格納 | 監査補助 |

### 3.2 GCP実態（IAM・リソース・グループ）収集系テーブル

#### `iam_policy_permissions` (GCPのIAM状態スナップショット)

Cloud Asset API から収集した、最新の現実のIAMバインディングです（洗い替え）。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `execution_id` | Python内部生成 | 収集ジョブの UUID | 履歴トレース |
| `assessment_timestamp`| Python実行日時 | ジョブ開始時のタイムスタンプ | データ鮮度の確認 |
| `scope` | 環境変数設定 | 対象プロジェクトまたは組織ID (`organizations/XXX`) | 収集範囲のメタデータ |
| `resource_type` | Cloud Asset API | `asset_type` (例: `cloudresourcemanager.googleapis.com/Project`) | 帳票表示、不整合検知 |
| `resource_name` | Cloud Asset API | `resource` (例: `//cloudresourcemanager.googleapis.com/projects/XXX`) | **全テーブルを跨ぐコア結合キー**、帳票表示 |
| `resource_id` | Pythonで加工抽出 | `resource_name` から正規表現で抽出（例: `XXX`） | 帳票表示 |
| `principal_type` | Cloud Asset API | `members` の接頭辞(`user:`, `serviceAccount:`) をPythonで正規化 | カタログ生成、帳票表示 |
| `principal_email` | Cloud Asset API | `members` の接頭辞以降のメールアドレス部分 | **全テーブルを跨ぐコア結合キー** |
| `role` | Cloud Asset API | `policy.bindings.role` | **全テーブルを跨ぐコア結合キー** |
| `iam_condition` | Cloud Asset API | 条件付きロールの `expression` を取得 | セキュリティ監査 |

#### `iam_policy_bindings_raw_history` (監査用の生履歴)

上記の `iam_policy_permissions` を日次で `WRITE_APPEND` していく生アーカイブです。スキーマ・源泉・用途は同一です。

#### `gcp_resource_inventory_history` (リソース階層の収集履歴)

Cloud Asset APIからGCPリソース（プロジェクト・フォルダ等）のツリー構造を収集します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `execution_id` | Python内部生成 | 収集ジョブの UUID | 履歴トレース |
| `assessed_at` | Python実行日時 | ジョブ開始時のタイムスタンプ | 帳票での「最新データ」抽出 |
| `resource_type` | Cloud Asset API | `asset_type` を `Project`, `Folder` 等の短縮名に変換 | 帳票表示 (`v_sheet_resource`) |
| `resource_name` | Cloud Asset API | `display_name` (例: "本番環境") または IDへのフォールバック | 帳票表示 (`v_sheet_resource`) |
| `resource_id` | Cloud Asset API | `project_id` や正規化されたIDを抽出 | 帳票表示 (`v_sheet_resource`) |
| `parent_resource_id`| Cloud Asset API | `parent_full_resource_name` を正規化して親IDを抽出 | 帳票表示、階層構造の把握 |
| `full_resource_path`| Cloud Asset API | APIが返した生の `name` を正規化したフルパス | このテーブル特有の階層把握用データ |
| `note` | Python静的文字列 | `source=cloudasset scope=XXX` をセット | メタデータ |

#### `principal_catalog`（User/Group/ServiceAccount 統合）

Cloud Identity / Admin SDK / IAM API から収集したプリンシパル一覧です。帳票では `v_sheet_principal` を参照します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `principal_email` | Cloud Identity / Admin SDK / IAM API | メールアドレスを正規化して主キー化 | 帳票表示、監査時の主結合キー |
| `principal_name` | Cloud Identity / Admin SDK / IAM API | `displayName` / `fullName` / `displayName` を採用 | 帳票表示 (`v_sheet_principal`) |
| `principal_type` | Cloud Identity / Admin SDK / IAM API | `GROUP` / `USER` / `SERVICE_ACCOUNT` に正規化 | 帳票表示 (`v_sheet_principal`) |
| `principal_status` | Cloud Run 同期ロジック | 当日収集で存在したものを `ACTIVE`、収集対象外になったものを `INACTIVE` | 帳票表示 (`v_sheet_principal`) |
| `deactivated_at` | Cloud Run 同期ロジック | `INACTIVE` へ遷移した日時を保持 | 監査・失効確認 |

#### `google_group_membership_history`

Cloud Identity API から収集したグループメンバーシップ情報です。帳票では `v_sheet_group_members` を参照します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `group_email` | Cloud Identity API | グループの `groupKey.id` | メンバーシップとの結合キー、帳票表示 |
| `member_email` | Cloud Identity API | メンバーシップの `preferredMemberKey.id` | 帳票表示 (`v_sheet_group_members`) |
| `membership_type` | Cloud Identity API | メンバーシップの `roles[0].name` (MEMBER/OWNER等) | 権限レベルの把握 |

### 3.3 監査・インシデント・マスタ関連テーブル

#### `iam_reconciliation_issues` (不整合アラート)

`iam_policy_permissions` (現実) と `iam_access_requests` (意図) を FULL OUTER JOIN した結果生じた矛盾です。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `issue_id` | BQ SQL生成 | `FORMAT('%s-%s-%s', request_id, issue_type, timestamp)` | インシデントの一意識別 |
| `issue_type` | BQ SQL判定 | `APPROVED_NOT_APPLIED`, `UNMANAGED_BINDING` 等のロジック判定結果 | アラート発報の分類、シート表示 |
| `request_id` | `iam_access_requests` | 該当する申請があればIDをセット | 申請追跡用 |
| `principal_email` | 両テーブルの結合 | 矛盾が発生した対象者 | シート表示 |
| `resource_name` | 両テーブルの結合 | 矛盾が発生したリソース | シート表示 |
| `role` | 両テーブルの結合 | 矛盾が発生したロール | シート表示 |
| `detected_at` | BQ SQL生成 | `CURRENT_TIMESTAMP()` | アラート発報日時、マージ判定 |
| `severity` | BQ SQL判定 | `HIGH`, `MEDIUM` 等のロジック判定結果 | シート表示での深刻度可視化 |
| `status` | BQ SQL生成 | 初期値 `OPEN` | GASでの未解決アラート抽出条件 |
| `details` | 両テーブルの結合 | `exists_now`, `expires_at` 等をJSON化 | 障害調査 |

#### `iam_pipeline_job_reports` (バッチ実行レポート)

非同期バッチ（収集・不整合検知・剥奪等）の結果を記録します。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination) |
| :--- | :--- | :--- | :--- |
| `execution_id` | Python内部生成 | 各バッチ処理の UUID | ジョブの一意識別 |
| `job_type` | Python静的文字列 | `RESOURCE_COLLECTION`, `IAM_RECONCILIATION` 等 | レポートの分類 |
| `result` | Python処理結果 | `SUCCESS`, `FAILED`, `FAILED_PERMISSION` | 稼働監視 |
| `error_code` / `error_message` | Python例外 | 発生した例外の情報 | 障害調査 |
| `counts` | Python処理結果 | 挿入行数などのメトリクスをJSON化 | 処理件数の監視 |

#### `principal_catalog` / `iam_status_master` (マスタ)

帳票表示を補助するためのデータです。

- **`principal_catalog`**: Cloud Identity / Admin SDK / IAM API の収集結果を `MERGE` し、メールアドレスごとの種別と有効状態（`ACTIVE`/`INACTIVE`）を保つマスタ。
- **`iam_role_master`**: `iam_policy_permissions` から未知のロールを検知し、Gemini APIで自動翻訳した結果を保持するマスタ。
- **`iam_status_master`**: SQL DDLで定義された、英語のステータスコードを日本語 (`APPROVED` -> `承認済`) に変換する静的マスタ。

### 3.4 最終出力（帳票・UI）系データリネージ

#### `iam_permission_bindings_history` (帳票用結合テーブル)

「GCPの現実」に「申請のコンテキスト（理由・承認者等）」を付与して整形した、本システムの集大成となるテーブルです。

| カラム名 | 源泉 (Source) | 加工・挿入 (Transform/Load) | 下流での用途 (Destination / 帳票名) |
| :--- | :--- | :--- | :--- |
| `execution_id` | Python内部生成 | 履歴更新ジョブの UUID | リネージトレース |
| `recorded_at` | BQ SQL生成 | `CURRENT_TIMESTAMP()` | 日次スナップショットの時刻 |
| `resource_name` | `iam_policy_permissions` | 現実のリソース名をそのまま取得 | **帳票：「リソース名」** |
| `resource_id` | `iam_policy_permissions` | 現実のリソースIDを取得 | **帳票：「リソースID」** |
| `principal_email` | `iam_policy_permissions` | 現実のアカウントをそのまま取得 | **帳票：「プリンシパル」** |
| `principal_type` | `iam_policy_permissions` | 現実のアカウント種別を取得 | **帳票：「種別」** |
| `iam_role` | `iam_policy_permissions` | 現実のロールを取得 | **帳票：「IAMロール」** |
| `iam_condition` | `iam_policy_permissions` | 現実の条件（式）を取得 | **帳票：「IAM Condition」** |
| `ticket_ref` | `iam_access_requests` | 該当する申請のチケット番号を結合 | **帳票：「申請チケット番号」** |
| `request_reason` | `iam_access_requests` | 該当する申請の `reason` を結合 | **帳票：「申請理由・用途」** |
| `status_ja` | `iam_status_master` | 該当申請のステータスを日本語化して結合 | **帳票：「ステータス」** |
| `approved_at` | `iam_access_requests` | 該当申請の承認日時を結合 | **帳票：「承認日」** |
| `next_review_at` | `iam_access_requests` | `expires_at` を `DATE` 型にCASTして結合 | **帳票：「次回レビュー日」** |
| `approver` | `iam_access_requests` | 該当申請の承認者メールを結合 | **帳票：「承認者」** |
| `request_id` | `iam_access_requests` | 該当する申請のID | 帳票内部のトレース用キー |
| `note` | BQ SQL静的文字列 | 'Snapshot from iam_policy_permissions' をセット | データの出所を識別 |

______________________________________________________________________

## 4. 監査と精査のポイント（アーキテクチャ上のリスクと防御）

このリネージマップを踏まえ、データエンジニアとして精査すべきポイントは以下の通りです。

1. **入力フォーマットの自動補完によるエラーの防止（バリデーションの壁）**
   - ユーザーが対象リソースに `my-project` のような短縮表記を入力した場合、GCP APIが要求する厳密な形式（`projects/my-project`）と一致せずエラーになるリスクがあります。この問題を防ぐため、GASのバックエンド（`Code.gs` の `normalizeResourceName_` 関数）でプレフィックス不足時に `projects/` を自動補完する防御層を設けています。
   - さらに、ロール名についてもフロントエンドから送信する前にAI（Gemini）を用いた厳格なタイポチェックが働くため、不正なフォーマットが下流（BigQueryやCloud Run）に流し込まれることはありません。
1. **グループのネスト（間接付与）という盲点**
   - UIの「IAM権限設定マトリクス」では、グループに付与された権限を展開して「個人の権限」として紐づけて可視化するSQLビューが存在しないため、監査時に「間接的に権限を持っているユーザー」を見落とすリスクがあります。
1. **Cloud Asset APIの遅延特性**
   - Cloud Runが実行（`setIamPolicy`）した直後に収集バッチが走った場合、Cloud Asset API側のインデックス更新遅延により、古いIAM状態が取得されることがあります。本システムでは、この特性を考慮し「ステータス変更から12時間は猶予期間（Grace Period）としてアラート発報を保留する」保護ロジックをSQL内に組み込むことで、偽陽性アラートの発報を防いでいます。

## 5. データ型のマッピングポリシー (Data Type Consistency)

システム全体を通じて、以下のデータ型マッピングポリシーを厳格に適用し、PythonアプリケーションとBigQuery間の型不一致エラー（Schema Mismatch）を防いでいます。

- **日時データ (Timestamps / Dates):**
  - **Python側:** `datetime.now(timezone.utc).isoformat()` (ISO 8601形式の文字列)
  - **BigQuery側:** `TIMESTAMP` 型。文字列として挿入されたISO 8601フォーマットはBigQueryにより自動的にTIMESTAMPにパースされます。
- **動的構造データ (Dynamic Structures):**
  - **Python側:** 任意のキーと値を持つ `dict`
  - **BigQuery側:** `JSON` 型。`RECORD` (STRUCT) 型はキーが事前に静的に決定できる場合にのみ使用し、レポートのメトリクス（`counts`）やトレースバック（`details`）のようなジョブごとにキーが変動する動的な構造には、必ず `JSON` 型を使用します。また、Pythonから辞書を送信する際は `json.dumps(ensure_ascii=False)` を用いて明示的にシリアライズします。
- **識別子・列挙値 (Identifiers / Enums):**
  - **Python側:** `str`
  - **BigQuery側:** `STRING` 型。UUID、メールアドレス、リソース名、`SUCCESS / FAILED` などのステータスはすべて文字列として扱います。
