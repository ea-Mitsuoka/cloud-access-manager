# BigQuery テーブル仕様書

本システムが利用する BigQuery テーブルの一覧と、ソースコードの実装に基づく正確な利用目的を定義します。

## 1. IAM・権限状態（スナップショットと履歴）

| テーブル名 | 更新方式 | 真の利用目的（プログラムの実態） | データの使い道 |
| :--- | :--- | :--- | :--- |
| **`iam_policy_permissions`** | 洗い替え (外部) | **最新のIAM状態スナップショット（読み取り専用）。** 外部システムが最新の権限状態で定期的に上書き（WRITE_TRUNCATE）する前提のテーブル。本システムは不整合検知や帳票作成のための「現状の正」として SELECT のみを行う。 | **・不整合検知の比較元**: 申請状態と実際の権限状態に差異がないかをチェックするための正解データとして利用。 <br>**・マスタ生成の源泉**: プリンシパル（アカウント）情報を抽出し、カタログを最新化するために利用。 |
| **`iam_policy_bindings_raw_history`** | 追記 | **生のIAM権限履歴アーカイブ（監査用）。** `iam_policy_permissions` のIAMの断面情報を、加工せずに日次バッチで追記していくための器。第三者の監査向け。 | **・外部監査**: 過去の特定の時点において、誰がどの権限を持っていたかを証明するための改ざん不可能な証跡として提出。 |
| **`iam_permission_bindings_history`** | 追記 | **帳票出力用の整形済みIAM権限履歴（レビュー用）。** 最新の `iam_policy_permissions` に対して、過去の申請内容（理由、承認者、チケット番号）を結合し、人間が棚卸しレビューしやすい形に整形して保存するテーブル。 | **・定期棚卸し**: 各部門のマネージャーやセキュリティ担当者が、現在付与されている権限の正当性（理由や承認者）をスプレッドシート上で確認・レビューするためのデータソース。 |

## 2. 申請・承認ワークフロー

| テーブル名 | 更新方式 | 真の利用目的（プログラムの実態） | データの使い道 |
| :--- | :--- | :--- | :--- |
| **`iam_access_requests`** | 追記＋更新 | **申請・承認の正本。** ユーザーがGoogleフォームから送信したリクエストの最新ステータス（PENDING, APPROVED 等）を管理する。GASやCloud Runによってステータスが随時 UPDATE される。 | **・実行エンジンの入力**: 承認された申請をCloud Runが読み取り、実際のIAM付与・剥奪処理を行うためのキューとして機能。 <br>**・有効期限管理**: 期限付き権限の失効日を管理し、自動剥奪バッチの対象を特定するために利用。 |
| **`iam_access_request_history`** | 追記 | **申請フローの完全な監査ログ（イベントログ）。** 申請のステータスが変わるたびに、「誰が・いつ・どう変更したか」と「その時点の申請理由のスナップショット」を追記する。一度書き込まれたデータは UPDATE されない。 | **・承認プロセスの監査**: 権限付与に至るまでの承認フローが正しく行われたか、誰が承認したかを事後確認するための証跡。 |

## 3. システム実行ログ・検知

| テーブル名 | 更新方式 | 真の利用目的（プログラムの実態） | データの使い道 |
| :--- | :--- | :--- | :--- |
| **`iam_access_change_log`** | 追記 | **Cloud RunによるAPI実行ログ。** 承認された申請に基づき、システムが実際にIAM API（GRANT/REVOKE）を呼び出した際の「成否（SUCCESS/FAILED）」とエラー内容を記録する。冪等性（二重実行防止）の判定にも使用される。 | **・実行ステータス確認**: 申請がシステムによって正しく処理されたか、失敗した場合はその理由を調査するためのログ。 <br>**・冪等性の担保**: 過去の成功履歴を確認し、同一申請の二重実行を防止する。 |
| **`iam_reconciliation_issues`** | 追記 | **不整合検知アラート。** 「承認済なのに権限が付与されていない」「却下されたのに権限が残っている」「期限切れなのに権限が残っている」など、意図（申請）と実態（IAM）の矛盾を検知して記録する。 | **・セキュリティインシデント調査**: 意図しない権限の残留や、システム外での直接的な権限変更（シャドーIT）を検知し、セキュリティチームが対応するためのアラート一覧。 |
| **`iam_pipeline_job_reports`** | 追記 | **非同期バッチの処理結果レポート。** リソース収集、グループ収集、不整合検知など、バックグラウンドで動く定期バッチジョブの実行結果や処理件数を記録する。 | **・システム運用監視**: 日次のバッチ処理が正常に完了しているか、データ収集漏れがないかをシステム管理者がモニタリングするためのレポート。 |

## 4. リソース・グループ棚卸し

| テーブル名 | 更新方式 | 真の利用目的（プログラムの実態） | データの使い道 |
| :--- | :--- | :--- | :--- |
| **`gcp_resource_inventory_history`** | 追記 | **GCPリソース構造の履歴。** Cloud Asset API から収集したプロジェクトやフォルダの情報を日次で追記する。 | **・リソース階層の把握**: 権限が付与されている対象リソースが、組織内のどの階層（フォルダ等）に属しているかを特定するためのマスタ情報。 |
| **`google_groups`** | 洗い替え | **Googleグループの一覧マスタ。** Cloud Identity API から収集した最新のグループ一覧。収集のたびに全件 DELETE & INSERT される。 | **・グループ情報の補完**: 権限が付与されている対象がグループの場合、そのグループの表示名や説明を帳票上で表示するためのマスタ。 |
| **`google_group_membership_history`**| 追記 | **グループメンバーシップの履歴。** どのグループに誰が所属しているかの変遷を日次で追記する。 | **・間接的な権限の監査**: グループに対して付与された権限が、実際にはどのメンバーに行き渡っているかを特定し、棚卸しレビューを詳細化するためのデータ。 |

## 5. 帳票用マスタ

| テーブル名 | 更新方式 | 真の利用目的（プログラムの実態） | データの使い道 |
| :--- | :--- | :--- | :--- |
| **`principal_catalog`** | MERGE | **帳票表示用のプリンシパルマスタ。** メールアドレスと種別（USER, SA等）を紐付ける。日次バッチにより最新のIAM情報から自動同期される。 | **・帳票の視認性向上**: スプレッドシート上でアカウントの種別（ユーザーかサービスアカウントか等）を明記し、レビューの精度を上げるために利用。 |
| **`iam_status_master`** | MERGE | **ステータス表示の制御マスタ。** スプレッドシート帳票上でステータスを日本語化し、適切な順番（sort_order）で表示するための固定マスタ。 | **・UI/UXの統一**: 申請のステータスをわかりやすい日本語で表示し、帳票上でのソート順をビジネスロジックに沿って正しく制御するために利用。 |

______________________________________________________________________

## テーブル詳細とスキーマ

### `iam_policy_bindings_raw_history`

- **利用目的:** 特定の時点におけるIAMポリシーバインディングの生データスナップショットを記録する監査用テーブル。
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | 収集ジョブのユニークな実行ID |
| `assessment_timestamp` | TIMESTAMP | NOT NULL | IAM設定が収集・評価された日時 |
| `scope` | STRING | NULLABLE | 収集対象のスコープ（例: 組織IDやプロジェクトID） |
| `resource_type` | STRING | NULLABLE | リソースの種別（Project, Folder, Organization 等） |
| `resource_name` | STRING | NULLABLE | 権限が付与されている対象リソース名 |
| `principal_type` | STRING | NULLABLE | 権限を持つアカウントの種別（User, ServiceAccount, Group 等） |
| `principal_email` | STRING | NULLABLE | 権限を持つアカウントのメールアドレス |
| `role` | STRING | NULLABLE | 付与されているIAMロール（roles/xxx） |

### `iam_access_requests`

- **利用目的:** IAMアクセスの申請および承認リクエストの正本データを記録し、ステータスを管理する。
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`, `apps-script/Code.gs`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `request_id` | STRING | NOT NULL | 申請の一意なID (UUID等) |
| `request_type` | STRING | NOT NULL | 申請の種類 (GRANT / REVOKE / CHANGE) |
| `principal_email` | STRING | NOT NULL | 権限付与・剥奪の対象となるアカウントのメールアドレス |
| `resource_name` | STRING | NOT NULL | 対象となるGCPリソース名 |
| `role` | STRING | NOT NULL | 付与・剥奪するIAMロール |
| `reason` | STRING | NULLABLE | 申請理由・利用目的 |
| `expires_at` | TIMESTAMP | NULLABLE | 権限の有効期限（恒久の場合はNULL） |
| `requester_email` | STRING | NOT NULL | 申請を行ったユーザーのメールアドレス |
| `approver_email` | STRING | NULLABLE | 承認者のメールアドレス |
| `status` | STRING | NOT NULL | 現在のステータス (PENDING / APPROVED / REJECTED / CANCELLED 等) |
| `requested_at` | TIMESTAMP | NOT NULL | 申請日時 |
| `approved_at` | TIMESTAMP | NULLABLE | 承認日時 |
| `ticket_ref` | STRING | NULLABLE | 関連する社内チケット等の参照番号 |
| `created_at` | TIMESTAMP | NOT NULL | レコード作成日時 |
| `updated_at` | TIMESTAMP | NOT NULL | レコード最終更新日時 |

### `iam_access_change_log`

- **利用目的:** Cloud Run が IAM API を呼び出して権限を変更した結果（API実行ログ）を記録する。
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`, `apps-script/Code.gs`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | API実行処理ごとのユニークID |
| `request_id` | STRING | NOT NULL | 紐づく申請のID |
| `action` | STRING | NOT NULL | 実行されたアクション (GRANT / REVOKE) |
| `target` | STRING | NOT NULL | アクションの対象リソース |
| `before_hash` | STRING | NULLABLE | 変更前のIAMポリシーのハッシュ値 |
| `after_hash` | STRING | NULLABLE | 変更後のIAMポリシーのハッシュ値 |
| `result` | STRING | NOT NULL | 実行結果 (SUCCESS / FAILED / SKIPPED) |
| `error_code` | STRING | NULLABLE | 失敗時のエラーコードまたは例外名 |
| `error_message` | STRING | NULLABLE | 失敗時の詳細なエラーメッセージ |
| `executed_by` | STRING | NULLABLE | APIを実行したサービスアカウント等の識別子 |
| `executed_at` | TIMESTAMP | NOT NULL | APIが実行された日時 |
| `details` | JSON | NULLABLE | スタックトレースなどの詳細情報 |

### `iam_access_request_history`

- **利用目的:** 申請のステータス変更履歴を監査証跡（イベントログ）として記録する。
- **主要なソース:** `sql/001_tables.sql`, `apps-script/Code.gs`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `history_id` | STRING | NOT NULL | 履歴レコードの一意なID |
| `request_id` | STRING | NOT NULL | 対象となる申請のID |
| `event_type` | STRING | NOT NULL | イベントの種別 (REQUESTED / STATUS_CHANGED) |
| `old_status` | STRING | NULLABLE | 変更前のステータス |
| `new_status` | STRING | NOT NULL | 変更後のステータス |
| `reason_snapshot` | STRING | NULLABLE | イベント発生時点での申請理由（後から改ざんできないように記録） |
| `request_type` | STRING | NULLABLE | スナップショット: 申請の種類 |
| `principal_email` | STRING | NULLABLE | スナップショット: 対象アカウント |
| `resource_name` | STRING | NULLABLE | スナップショット: 対象リソース |
| `role` | STRING | NULLABLE | スナップショット: 対象ロール |
| `requester_email` | STRING | NULLABLE | スナップショット: 申請者 |
| `approver_email` | STRING | NULLABLE | スナップショット: 承認者 |
| `acted_by` | STRING | NULLABLE | イベントを引き起こしたユーザーまたはシステム |
| `actor_source` | STRING | NULLABLE | イベントの発生元 (FORM_SUBMIT / SHEET_EDIT / API 等) |
| `event_at` | TIMESTAMP | NOT NULL | イベント発生日時 |
| `details` | JSON | NULLABLE | その他の付加情報 |

### `iam_reconciliation_issues`

- **利用目的:** 意図（申請状態）と実態（IAM状態）の間の矛盾（不整合）を検出し、アラートとして記録する。
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `issue_id` | STRING | NOT NULL | 不整合の検知一意識別子 |
| `issue_type` | STRING | NOT NULL | 不整合の種別 (APPROVED_NOT_APPLIED / REJECTED_BUT_EXISTS 等) |
| `request_id` | STRING | NULLABLE | 関連する申請ID（存在する場合） |
| `principal_email` | STRING | NULLABLE | 問題が起きているアカウント |
| `resource_name` | STRING | NULLABLE | 問題が起きているリソース |
| `role` | STRING | NULLABLE | 問題が起きているロール |
| `detected_at` | TIMESTAMP | NOT NULL | 不整合が検知された日時 |
| `severity` | STRING | NOT NULL | 深刻度 (HIGH / MEDIUM 等) |
| `status` | STRING | NOT NULL | 問題の対応ステータス (OPEN 等) |
| `details` | JSON | NULLABLE | デバッグや調査に必要な詳細情報 |

### `iam_pipeline_job_reports`

- **利用目的:** システムのバックグラウンドで実行される非同期バッチジョブ（収集や棚卸し）の実行結果を記録する。
- **主要なソース:** `sql/001_tables.sql`, `terraform/modules/bigquery/main.tf`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | バッチ処理の実行ID |
| `job_type` | STRING | NOT NULL | ジョブの種類 (RESOURCE_COLLECTION / GROUP_COLLECTION 等) |
| `result` | STRING | NOT NULL | 実行結果 (SUCCESS / FAILED_PERMISSION / FAILED) |
| `error_code` | STRING | NULLABLE | 失敗時のエラーコードや例外名 |
| `error_message` | STRING | NULLABLE | エラーの詳細メッセージ |
| `hint` | STRING | NULLABLE | エラー解決のための運用ヒント |
| `counts` | JSON | NULLABLE | 処理された件数（挿入行数など）のメトリクス |
| `details` | JSON | NULLABLE | その他の詳細情報 |
| `occurred_at` | TIMESTAMP | NOT NULL | ジョブが終了・記録された日時 |

### `principal_catalog`

- **利用目的:** システム内で参照されるプリンシパル（アカウント）のマスターデータを管理する。
- **主要なソース:** `sql/004_workbook_tables.sql`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `principal_email` | STRING | NOT NULL | プリンシパルのメールアドレス（主キー） |
| `principal_name` | STRING | NULLABLE | プリンシパルの表示名 |
| `principal_type` | STRING | NULLABLE | アカウント種別（User, ServiceAccount, Group 等） |
| `note` | STRING | NULLABLE | 管理用の備考 |
| `updated_at` | TIMESTAMP | NOT NULL | レコードの最終更新日時 |

### `google_groups`

- **利用目的:** Cloud Identityから収集されたGoogleグループの一覧を保持する（洗い替えマスタ）。
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `group_email` | STRING | NOT NULL | グループのメールアドレス（主キー） |
| `group_name` | STRING | NULLABLE | グループの表示名 |
| `description` | STRING | NULLABLE | グループの説明文 |
| `source` | STRING | NULLABLE | データの収集元 (cloudidentity 等) |
| `updated_at` | TIMESTAMP | NOT NULL | 収集・更新された日時 |

### `google_group_membership_history`

- **利用目的:** Googleグループのメンバー所属状況（誰がどのグループにいるか）の変遷を記録する。
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | 収集ジョブの実行ID |
| `assessed_at` | TIMESTAMP | NOT NULL | 情報が収集された日時 |
| `group_email` | STRING | NOT NULL | 親となるグループのメールアドレス |
| `member_email` | STRING | NOT NULL | 所属しているメンバーのメールアドレス |
| `member_display_name` | STRING | NULLABLE | メンバーの表示名 |
| `membership_type` | STRING | NULLABLE | メンバーシップの種別やロール（MEMBER, OWNER 等） |
| `source` | STRING | NULLABLE | データの収集元 |

### `gcp_resource_inventory_history`

- **利用目的:** Cloud Asset APIから収集したGCPリソース（プロジェクト、フォルダ等）の階層構造の履歴を記録する。
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | 収集ジョブの実行ID |
| `assessed_at` | TIMESTAMP | NOT NULL | 情報が収集された日時 |
| `resource_type` | STRING | NOT NULL | リソースの種別 (Project, Folder 等) |
| `resource_name` | STRING | NULLABLE | リソースの表示名 |
| `resource_id` | STRING | NOT NULL | リソースの一意なID |
| `parent_resource_id` | STRING | NULLABLE | 親リソースのID（階層構造の表現） |
| `full_resource_path` | STRING | NULLABLE | リソースの完全なパス |
| `note` | STRING | NULLABLE | 収集時の備考やスコープ情報 |

### `iam_status_master`

- **利用目的:** スプレッドシート等の帳票でステータスを日本語化・ソート順制御するためのマスタデータ。
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `status_ja` | STRING | NOT NULL | 日本語でのステータス表示名 |
| `status_code` | STRING | NULLABLE | システムで扱うステータスコード |
| `description` | STRING | NULLABLE | ステータスの意味や説明 |
| `sort_order` | INT64 | NULLABLE | 帳票で表示する際のソート順 |
| `is_active` | BOOL | NOT NULL | このステータスが現在利用可能かどうか |
| `updated_at` | TIMESTAMP | NOT NULL | レコードの最終更新日時 |

### `iam_permission_bindings_history`

- **利用目的:** 人間が棚卸しレビューを行うために、IAM権限の履歴に申請理由や承認者などの文脈を結合した整形済みテーブル。
- **主要なソース:** `sql/004_workbook_tables.sql`, `cloud-run/app/repository.py`

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | データ作成ジョブの実行ID |
| `recorded_at` | TIMESTAMP | NOT NULL | データが記録された日時 |
| `resource_name` | STRING | NULLABLE | 権限が付与されているリソース名 |
| `resource_id` | STRING | NULLABLE | リソースの一意識別子 |
| `principal_email` | STRING | NOT NULL | 権限を持つアカウントのメールアドレス |
| `principal_type` | STRING | NULLABLE | アカウント種別 |
| `iam_role` | STRING | NOT NULL | 付与されているIAMロール |
| `iam_condition` | STRING | NULLABLE | IAM Condition（条件付きロールの場合） |
| `ticket_ref` | STRING | NULLABLE | 申請時のチケット参照番号 |
| `request_reason` | STRING | NULLABLE | 申請理由（申請履歴から結合） |
| `status_ja` | STRING | NULLABLE | 帳票表示用の日本語ステータス |
| `approved_at` | TIMESTAMP | NULLABLE | 承認日時（申請履歴から結合） |
| `next_review_at` | DATE | NULLABLE | 権限の有効期限・次回レビュー期日 |
| `approver` | STRING | NULLABLE | 承認者（申請履歴から結合） |
| `request_id` | STRING | NULLABLE | 関連する申請のID |
| `note` | STRING | NULLABLE | 記録時の備考 |

### `iam_policy_permissions`

- **利用目的:** 外部システムによって定期的に上書きされる、現在のIAMポリシーの「正」となる状態。このシステムからは**読み取り専用**として扱われる。洗い替えテーブル。
- **主要なソース:** `cloud-run/app/repository.py` (参照のみ), `sql/*.sql` (参照のみ)

| カラム名 | 型 | NULL | 説明 |
| :--- | :--- | :--- | :--- |
| `execution_id` | STRING | NOT NULL | 1回の評価実行を一意に識別するUUID |
| `assessment_timestamp` | TIMESTAMP | NOT NULL | 評価日時 |
| `scope` | STRING | NOT NULL | 収集スコープ |
| `resource_type` | STRING | NOT NULL | リソースの種類 |
| `resource_name` | STRING | NOT NULL | 具体的なリソース名 |
| `principal_type` | STRING | NULLABLE | アカウントの種別 |
| `principal_email` | STRING | NULLABLE | アカウントのメールアドレス |
| `role` | STRING | NOT NULL | 付与されているIAMロール |
