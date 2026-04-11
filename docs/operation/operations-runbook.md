# Cloud Access Manager 運用手順書

## 1. 緊急時の対応（Break-glass フロー）

システム障害時など、通常の承認プロセス（スプレッドシートでのレビュー）を待つ時間がない一刻を争う事態のための手順です。
（※旧仕様の申請UIでの選択肢追加は廃止されました。現在はSaaSポータルから直接トリガー可能です）

**【発動手順】**

1. **緊急申請 (トリガー):**
   申請者は **SaaSポータル（申請Webアプリ）** にアクセスし、申請種別のプルダウンから **「緊急付与」** を選択してリクエストを送信します。
   ※理由欄に必ず「インシデント番号（例: INC-1234）」や「障害の状況」を明記してください。
1. **即時自動付与:**
   人間の承認フローを完全にバイパスし、システム（Cloud Run）が数秒以内にGCPへ対象権限を自動付与します。
1. **管理者への強烈なアラート発報:**
   権限付与と同時に、システム管理者およびSOC（セキュリティ監視チーム）へ `[BREAK-GLASS] 緊急アクセス発動` のアラートが即時通知されます。

**【事後対応】**

- 障害対応が完了次第、管理者は監査ログ（BigQuery）の記録をもとに事後監査を行い、付与された権限を速やかに手動で剥奪してください（またはシステムの期限切れ自動剥奪を待ちます）。

## 2. Cloud Scheduler の実行順序制約

日次バッチは、時刻を自由に変更できますが、次の依存順序を崩さないでください。

1. `revoke_expired_permissions`（期限切れ剥奪）
1. `collect/resources`, `collect/principals`, `collect/iam-policies`（現況収集）
1. `reconcile`（申請と現況の突合）
1. `jobs/update-iam-bindings-history`（帳票向け履歴更新）
1. `jobs/discover-iam-roles`（未知ロール発見・翻訳）

推奨理由:

- `reconcile` は最新の `iam_policy_permissions` を前提に判定するため、`collect/iam-policies` より後に実行する必要があります。
- `jobs/discover-iam-roles` は `iam_policy_permissions` から未知ロールを抽出するため、収集系の後に実行する必要があります。
- 剥奪処理を先に走らせることで、期限切れ権限を含まない状態で突合できます。

補足:

- `scripts/bootstrap-deploy.sh` は実行前に順序を検証し、逆転している場合は停止します。
- Terraform 側にも順序ガード（`scheduler_order_guard`）を実装しており、`terraform apply` 直実行でも順序違反を拒否します。

## 2.1 IAP有効化の切替手順（Phase 0 / Part 1）

`ENABLE_IAP=true` への切替は、以下の順序で実施してください。

1. `saas.env` に IAP 設定を入力します（`ENABLE_IAP=true`, `IAP_OAUTH_CLIENT_ID`, `IAP_OAUTH_CLIENT_SECRET`, `IAP_ALLOWED_PRINCIPALS`）。
1. `IAP_ALLOWED_PRINCIPALS` に、まず運用者ユーザー（最低1名）を追加します。
1. Cloud Run 実行サービスに対する IAP 通過ロールを付与します（Terraform適用）。
   - 付与順序:
     1. 運用者ユーザー（動作確認用）
     1. GAS 実行主体（必要な場合）
     1. Cloud Scheduler 実行主体（必要な場合）
1. `bash scripts/sync-config.sh` を実行して設定を反映します。
1. `bash scripts/bootstrap-deploy.sh --skip-apply` で生成物確認後、通常の `bootstrap-deploy.sh` または `terraform apply` を実行します。
1. 切替直後に以下を確認します。
   - `/healthz` へのアクセス（運用者）
   - GAS からの API 呼び出し
   - Cloud Scheduler の日次ジョブ（`RESOURCE_COLLECTION`, `PRINCIPAL_COLLECTION`, `IAM_POLICY_COLLECTION`）が `iam_pipeline_job_reports` で `SUCCESS` または `PARTIAL_SUCCESS`

補足:

- 本システムは移行互換のため、バックエンドで OIDC audience を `run.app URL` と `IAP_OAUTH_CLIENT_ID` の両方受け入れます。
- そのため段階移行（先にIAP有効化、後から呼び出し主体を順次切替）でも停止しにくい構成です。

## 3. テナント・オンボーディングと初期データ収集

SaaS基盤のデプロイ完了後、以下の手順で顧客環境の初期データを収集し、システムを稼働可能な状態にします。

1. （既存環境からの移行時のみ）旧設計でTerraformが管理していた「顧客側IAM付与リソース」をStateから切り離します。\
   ※ `scripts/bootstrap-deploy.sh` 実行時はこの処理を自動で実施しますが、手動 `terraform apply` の場合は先に実行してください。

   ```bash
   cd terraform
   terraform state list | grep -E '^(google_project_iam_member\.executor_managed_project_roles|google_organization_iam_member\.executor_managed_organization_roles)' | while read -r r; do terraform state rm "$r"; done
   ```

1. 顧客のIT管理者に `docs/customer/tenant-workspace-setup-guide.md` を渡し、自社のSaaS用サービスアカウントに対するIAM権限（Google WorkspaceおよびGoogle Cloud）の付与を依頼します。

1. 顧客から「権限付与完了」の連絡を受けたら、以下のどちらかの方法で初期データ収集を実施します。

   ```bash
   # 推奨: ワンコマンド
   bash scripts/onboard-tenant.sh
   ```

<details><summary>※スクリプトが使えない環境で手動実行する場合</summary>

```bash
bash scripts/collect-resource-inventory.sh
bash scripts/collect-principals.sh
bash scripts/collect-iam-policies.sh
```

</details>

1. 収集ジョブが `SUCCESS`（または必要に応じて `PARTIAL_SUCCESS`）で完了していることを、`iam_pipeline_job_reports` で確認します。

   ```bash
   bq query --project_id="your-tool-project-id" --use_legacy_sql=false '
   SELECT job_type, result, error_code, error_message, occurred_at
   FROM `your-tool-project-id.iam_access_mgmt.iam_pipeline_job_reports`
   WHERE job_type IN ("RESOURCE_COLLECTION","PRINCIPAL_COLLECTION","IAM_POLICY_COLLECTION")
   ORDER BY occurred_at DESC
   LIMIT 20'
   ```

1. 収集結果を確認した後、初期マスタおよび履歴データを生成するためのSQLをBigQuery上で実行します。

   ```bash
   # プロジェクトID等はご自身の環境に合わせてください
   bq query --project_id="your-tool-project-id" --use_legacy_sql=false < build/sql/007_seed_workbook_from_existing.sql
   ```

1. 以上でシステムのバックエンド準備は完了です。続いて「4. 管理用スプレッドシートの基本セットアップ」に進んでください。

## 4. 管理用スプレッドシートの基本セットアップ

1. **スプレッドシートの新規作成**: Googleドライブ等から、新しい空のスプレッドシートを作成し、任意の名前（例：「Cloud Access Manager 管理表」）を付けます。
1. **GASのデプロイ**: 作成したスプレッドシートのメニューから `拡張機能 > Apps Script` を開き、`apps-script/` フォルダ内の3つのコードを貼り付けます。
1. **初期設定**: 詳細は `apps-script/README.md` の手順に従い、環境変数の登録、マニフェスト（oauthScopes）の追加、および時間主導トリガー（`refreshRequestReviewStatus_` : 新規取り込みとステータス同期）を設定してください。
1. **シートの保護（セキュリティ設定: 推奨）**:
   一般ユーザーによる不正な承認操作を防ぐため、スプレッドシート標準の「範囲の保護」機能を利用してUIレベルで編集をブロックします。バックエンド側の認可制御と併用することで、最も堅牢なセキュリティを実現できます。
   - `requests_review` シートを開きます。
   - ステータスを更新する列（またはシート全体）を選択し、右クリックから「セルでのプルダウンなどの操作」>「範囲を保護」を選択します。
   - 編集権限を「自分のみ」や「特定の承認者グループ（Googleグループ）」に限定します。

### 4.1. Connected Sheets による監査データの取り込み（可視化）

BigQuery に構築された帳票用の整形済みビュー（`v_sheet_*`）をスプレッドシートの各タブに接続します。

1. スプレッドシートのメニューから **`データ > データコネクタ > BigQueryに接続`** を選択します。
1. GCPプロジェクトの選択画面が出るので、本システムをデプロイした `TOOL_PROJECT_ID` を選択します。
1. データセット一覧から `iam_access_mgmt`（または設定したデータセット名）を選択します。
1. テーブルとビューの一覧が表示されるので、以下のビューを選択して「接続」をクリックします（各ビューごとに新しいシートタブが作成されます）。
   - `v_sheet_iam_permission_history` （IAM権限設定履歴：メインの棚卸し帳票）
   - `v_sheet_requests_review` （申請レビュー用ビュー）
   - `v_sheet_principal` （プリンシパル一覧: User/Group/ServiceAccount統合）
   - `v_sheet_group_members` （グループメンバー一覧）
   - `v_sheet_resource` （リソース一覧）
   - `v_sheet_status` （ステータスマスタ）
1. 接続された各シートで、必要に応じて「スケジュールされた更新」を設定します（例: 毎朝8時に自動更新など）。これにより、前夜のバッチで収集・整形された最新のIAM監査データが、スプレッドシートを開くたびに自動で反映されます。

### 4.2. 「IAM権限設定マトリクス」の作成（ピボットテーブル）

Connected Sheetsで取り込んだ `v_sheet_iam_permission_history` （IAM権限設定履歴）のデータを元に、全体を俯瞰できるマトリクス表を作成します。

1. GASのカスタムメニュー（画面上部の `棚卸し > マトリクス更新`）をクリックします。
   *(※手動で行う場合は、`v_sheet_iam_permission_history` のシートからピボットテーブルを作成し、行に「リソース名」「プリンシパル」、列に「IAMロール」、値に「ステータス(COUNTA)」を設定してください)*
1. これにより、誰が・どのリソースに・何の権限を持っているかが一目でわかるクロス集計表（マトリクス）が完成します。

## 5. ランニングコスト（GCP料金）と最適化

本システムのアーキテクチャ（Google Workspace + サーバーレスGCP）は、\*\*「アイドル時の固定費がゼロ（Scale-to-Zero）」\*\*である点が最大の強みです。
一般的な中小〜中堅企業規模（月間100〜500件程度の申請、日次の自動棚卸しバッチ稼働）であれば、\*\*Google Cloudの月額費用は数十円〜数百円（ほぼ無料枠内）\*\*に収まる想定です。

### 5.1 月額費用の見積もり目安（月間300件の申請を想定）

| GCPサービス | 役割 | 想定利用量と料金概算（月額） |
| :--- | :--- | :--- |
| **Cloud Run** | 実行エンジン・バッチ処理 | **約 0 円**<br>月間数千秒の実行時間。GCPの無料枠に完全に収まります。 |
| **Cloud Scheduler** | 日次バッチのトリガー | **約 60円 ($0.40)**<br>無料枠（3ジョブ/月）を超える4ジョブ分について、1ジョブあたり$0.10かかります。 |
| **BigQuery** | 監査ログ・データ保存 | **約 0 円**<br>ストレージ（毎月10GBまで無料）、クエリ（毎月1TBまで無料）。 |
| **Artifact Registry** | コンテナイメージの保存 | **約 100〜300円**<br>1GBあたり約$0.10。 |
| **Cloud Asset/Identity API** | リソース・グループの収集 | **約 0 円**<br>無料枠内です。 |
| **Vertex AI (Gemini)** | ロール提案アシスタント | **数円**<br>Gemini 2.5 Flashを使用。非常に安価です。 |
| **Cloud Storage** | Terraform状態管理 | **約 0 円**<br>毎月5GBまで無料。 |
| **Google Workspace** | 申請UI・承認・帳票・GAS | **追加費用なし** |

**💰 月額合計の目安： 約 200円 程度**

### 5.2 コスト最適化の運用ポイント

このシステムは放置していても費用が跳ね上がることは基本的にありませんが、以下の点だけ運用に組み込んでおくと完璧です。

**1. Artifact Registry のクリーンアップポリシー設定（推奨）**
古いDockerイメージが蓄積され、ストレージ費用（月額数百円〜数千円）が徐々に増加するのを防ぐため、クリーンアップポリシーを設定することを強く推奨します。

GCPコンソールの「Artifact Registry」> リポジトリ（iam-access-repo）を選択 > 「クリーンアップポリシー」タブ から設定するか、以下のgcloudコマンドを利用してください。

```bash
# policy.json という名前で以下の内容を保存します
# [
#   {
#     "name": "delete-older-than-30d",
#     "action": {"type": "Delete"},
#     "condition": {"tagState": "ANY", "olderThan": "30d"}
#   }
# ]

# ポリシーを適用します
gcloud artifacts repositories set-cleanup-policies iam-access-repo --project="YOUR_PROJECT" --location="YOUR_REGION" --policy=policy.json
```

**2. BigQuery の長期保存（自動適用）**
監査ログは永遠に追記されていきますが、90日以上更新されないデータは自動的に「長期保存ストレージ」として料金が半額になるため、明示的なデータ削除（パージ）処理は不要です。

## 6. IAMロールマスタの運用（Human-in-the-Loop）

本システムは、未知のIAMロールを検知すると毎朝のバッチ (`iam-role-discovery-daily`) でGemini APIを呼び出し、日本語訳を自動生成して `iam_role_master` に登録します。

運用担当者は定期的に（例：月1回）以下の手順でAIの翻訳結果をレビューし、必要に応じて修正してください。この「人間によるレビューと修正」を前提とした運用設計（Human-in-the-Loop）により、運用の省力化と翻訳精度の両立を実現しています。

1. BigQueryコンソールを開き、`iam_role_master` テーブルを確認します。
1. `is_auto_translated = TRUE` となっているレコードが、AIによって自動翻訳されたまま未確認のロールです。
1. 翻訳内容（`role_name_ja`）に違和感がある場合、または公式な名称に固定したい場合は、以下のSQLで手動修正してください。

```sql
UPDATE `YOUR_PROJECT.YOUR_DATASET.iam_role_master`
SET role_name_ja = '正しい日本語名', is_auto_translated = FALSE, updated_at = CURRENT_TIMESTAMP()
WHERE role_id = 'roles/target.role';
```
