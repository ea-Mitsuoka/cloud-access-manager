Cloud Access Managerのバックエンド（Cloud Run）からBigQueryへの直接書き込みを廃止し、**Cloud Logging（構造化ログ）とLog Router Sinkを経由する疎結合な監査ログ基盤へと移行する**ための設計方針と要件定義書を作成しました。

今後の開発やTerraform改修のマスタードキュメントとしてご活用ください。

______________________________________________________________________

# Cloud Access Manager: 監査ログ基盤アーキテクチャ変更設計書

## 1. 背景と目的

現在のシステムは、PythonバックエンドからBigQueryのAPI（クライアントライブラリ）を直接呼び出し、監査ログ（申請履歴や実行結果）を書き込んでいる。これをGoogle Cloudネイティブな**Cloud Logging（構造化ログ）経由の非同期書き込みアーキテクチャ**へ変更する。

**【目的】**

1. **バックエンドの疎結合化と堅牢性向上:** BigQueryのスキーマ管理や通信エラーの再送処理（リトライ）をPython側から排除し、システムをシンプルかつ堅牢にする。
1. **エンタープライズの可観測性（Observability）強化:** すべてのイベントをCloud Loggingに集約することで、顧客の既存SIEM（Datadog, Splunk等）やSecurity Command Center (SCC)とのシームレスな統合を可能にする。
1. **データ主権（BYOC）の証明:** 「SaaS側はログを中継・保持せず、顧客環境の標準ロギング基盤にのみ出力する」というゼロトラスト設計を技術的に担保する。

## 2. 新旧アーキテクチャの比較

| 項目 | 旧アーキテクチャ（現状） | 新アーキテクチャ（変更後） |
| :--- | :--- | :--- |
| **データ書き込み** | Python → BigQuery API (Insert) | Python → `stdout` (JSON) → Cloud Logging |
| **テーブル作成** | Terraformで固定スキーマを定義 | Log Router SinkがRawテーブルを自動生成・追記 |
| **スプシからの参照** | 物理テーブルを直接参照 | 生ログをパース・整形した **View（仮想テーブル）** を参照 |
| **インフラエラー耐性** | BQダウン時にデータロストのリスク有 | Cloud Loggingがバッファリングし自動再送 |

## 3. システム設計とデータフロー

1. **イベント発生:** Cloud Run上のPythonアプリケーションが、IAM変更などのイベント発生時に、構造化されたJSONオブジェクトを標準出力（`stdout`）に出力する。
1. **ログの収集:** Google Cloudの基盤がJSONを自動検知し、Cloud Loggingの `jsonPayload` として格納する。
1. **ルーティング:** Log Router Sink が、特定のフィルタ条件（例: `jsonPayload.system = "cloud-access-manager"`）に合致するログをフックし、BigQueryデータセットへストリーミング転送する。
1. **ビューによる整形:** BigQuery上のViewが、入れ子になった `jsonPayload` をフラットな表形式に展開する。
1. **クライアント連携:** スプレッドシート（Connected Sheets / GAS）は、このViewを参照することで、従来通りのマトリクス生成や履歴閲覧を行う。

## 4. 実装要件・改修方針

### 4.1. バックエンド (Python) の改修

- **BigQuery SDKの排除:** `google-cloud-bigquery` ライブラリへの依存、および `insert_rows_json` などのDB操作ロジックをすべて削除する。
- **構造化ログ（JSON）出力の実装:** `logging` モジュールを改修し、以下のフォーマットに準拠したJSONを標準出力にプリントする実装に変更する。
- **相関IDの引き回し:** リクエストごとに一意の `ticket_id` （スプレッドシート上の申請番号等）を発行・受領し、全ログに含める。

**【出力JSONスキーマ例】**

```json
{
  "system": "cloud-access-manager",
  "ticket_id": "REQ-158293",
  "event_type": "ACCESS_GRANTED",
  "actor_email": "manager@example.com",
  "target_principal": "taro.yamada@example.com",
  "target_resource": "projects/my-project",
  "role": "roles/bigquery.dataViewer",
  "status": "SUCCESS",
  "details": {
    "reason": "GAデータパイプライン構築のため",
    "expires_at": "2026-04-30T23:59:59Z"
  }
}
```

### 4.2. クラウドインフラ (Terraform) の改修

顧客のGCP環境（データプレーン）に展開するTerraformモジュールに以下のリソースを追加・修正する。

- **Log Router Sink の作成 (`google_logging_project_sink`)**
  - **Destination:** 監査用のBigQueryデータセット。
  - **Filter:** `jsonPayload.system="cloud-access-manager"`
- **権限付与:** Sink専用のサービスアカウントに対し、対象データセットへの書き込み権限（`roles/bigquery.dataEditor`）を付与する。

### 4.3. データストア (BigQuery) の設計

Cloud LoggingからエクスポートされたRawデータ（例: `cloud_access_manager_logs_YYYYMMDD`）に対して、スプレッドシートが読み取るためのView（仮想テーブル）を構築する。

- **View の作成 (`v_iam_access_request_history`)**

  ```sql
  SELECT
    timestamp AS created_at,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.ticket_id') AS ticket_id,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.event_type') AS event_type,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.actor_email') AS approver,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.target_principal') AS principal,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.target_resource') AS resource_name,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.role') AS role,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.status') AS status,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.details.reason') AS reason
  FROM
    `your_project.your_dataset.raw_audit_logs`
  WHERE
    JSON_EXTRACT_SCALAR(jsonPayload, '$.system') = "cloud-access-manager"
  ```

  *(※Terraformの `google_bigquery_table` リソースの `view` ブロックで定義する)*

### 4.4. クライアント (スプレッドシート/GAS) の影響

- **UI/GASコードの改修:** **原則不要。**
- BigQueryのデータコネクタ（Connected Sheets）が参照する先を、物理テーブルから上記で作成したView（`v_iam_access_request_history` 等）へ変更する設定作業のみを実施する。

## 5. 非機能要件・運用設計

- **遅延（レイテンシ）の許容:** Log RouterからBigQueryへのストリーミング挿入には数秒〜最大数分程度の遅延が発生する可能性がある。監査業務においてこの遅延は許容範囲内とする。
- **ログの保持期間（ライフサイクル）:** BigQuery上のデータセットに対して、監査要件に基づいたパーティション分割とデータの有効期限（例: 3年〜5年）をTerraformで設定する。Cloud Logging本体の保持期間（デフォルト30日）はコスト最適化のため延長しない。
- **アラート・インシデント管理:** Cloud Loggingの「ログベースのアラート」機能を用い、`jsonPayload.event_type="EMERGENCY_BREAKGLASS"` などの重要イベントを検知し、管理者へ即時通知（メール/PubSub）する仕組みを構築する。

## 6. 将来の拡張性

- **SIEM連携:** 顧客から「Datadogに監査ログを送りたい」という要望が出た場合、システムコード（Python）は一切変更せず、TerraformでLog RouterのDestinationをPub/SubやSplunk等へ向けるだけで即座に対応可能。
- **マルチクラウド監査:** AWS（CloudTrail）やAzureのログ形式を模した `jsonPayload` を設計することで、マルチクラウド環境における統合監査基盤へと拡張できる。
