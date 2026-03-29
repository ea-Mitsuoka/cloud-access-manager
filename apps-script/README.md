# Apps Script セットアップ

## 1. スクリプトプロパティ

`プロジェクト設定 > スクリプトプロパティ` で以下の値を設定してください。

- `BQ_PROJECT_ID`
- `BQ_DATASET_ID`
- `BQ_LOCATION`
- `CLOUD_RUN_EXECUTE_URL` (例: `https://<service-url>/execute`)
- `GAS_INVOKER_SA_EMAIL` (必須: Terraform outputの gas_invoker_service_account を設定)

ルートの設定ファイルから以下のコマンドでJSONとして生成できます:

```bash
bash scripts/sync-config.sh
cat apps-script/script-properties.json
```

## 2. サービスの有効化

- `サービス` -> `BigQuery API` を追加 (Googleの拡張サービス)
- リンクされたGoogle Cloudプロジェクトでも、BigQuery APIを有効化してください。

## 3. トリガー

インストール可能なトリガーを作成します:

- `onFormSubmit`: スプレッドシートから、イベントのソース `スプレッドシートから`、イベントの種類 `フォーム送信時`
- `onEdit`: スプレッドシートから、イベントのソース `スプレッドシートから`、イベントの種類 `編集時`

`onFormSubmit` の動作:

- フォームから送信された内容をBigQueryの `iam_access_requests` テーブルに `PENDING` ステータスで記録します。
- 監査証跡として `iam_access_request_history` に `REQUESTED` イベントを記録します。
- `requests_review` シートに新しい行として申請内容を追記します。

`onEdit` の動作:

- `requests_review.status` が更新されると、ステータスがBigQueryに同期されます。
- 編集されたステータスが `承認済` または `APPROVED` の場合、Cloud Runの `/execute` が自動的に呼び出されます。
- ステータス更新後、`実行結果 / 最終反映確認 / 最終確認時刻` が `requests_review` シートで更新されます。
- `利用目的` は申請・承認履歴テーブル `iam_access_request_history` にスナップショットとして保存されます（監査向け）。

### 3.1 緊急アクセス（Break-glass）フロー

- **トリガー:** フォームの「申請種別」に「緊急」または「緊急付与」というキーワードが含まれていた場合、`onFormSubmit` 内で特別なフローが発動します。
- **動作:**
  1. 通常通り、申請内容が `PENDING` ステータスでBigQueryに記録されます。
  1. 直後に、スクリプトがシステム (`SYSTEM_AUTO_APPROVE`) として自動的にステータスを `APPROVED` に更新し、その履歴も記録します。
  1. 人間の承認を待たずに、即座にCloud Runの `/execute` エンドポイントを呼び出し、権限を付与します。
- **目的:** このフローは、システム障害対応など、一刻を争う事態のために用意されています。実行されると、その内容は**強い警告として管理者に即時通知**されます。統制と監査証跡を完全に担保しつつ、緊急時の迅速な対応を可能にします。

ピボット操作（データ整形なし）:

- `refreshIamMatrixPivotFromHistory()` を実行すると、`IAM権限設定履歴` シートから直接、スプレッドシートネイティブのピボットテーブル機能を使って `IAM権限設定マトリクス` が生成されます。
- カスタムメニュー `棚卸し > マトリクス更新` も利用できます。

レビュー状況の同期:

- `refreshRequestReviewStatus_()` を実行すると、BigQueryの実行結果や実際のIAM状態から `requests_review` シートが更新されます。
- カスタムメニュー `棚卸し > 申請反映ステータス更新` も利用できます。
- 継続的な可視性のために、時間駆動トリガー（例: 15分ごと）を推奨します。

## 4. 必須のフォーム項目ラベル

このスクリプトは、フォームの回答から以下の日本語ラベルを読み取ります:

- `申請種別`: 「新規付与」「変更」「削除」の他、**「緊急付与」**（または「緊急」を含む文字列）を指定すると、Break-glassフローがトリガーされます。
- `対象プリンシパル`
- `対象リソース`
- `付与・変更ロール`
- `申請理由・利用目的`
- `申請者メール`
- `承認者メール（または承認グループ）`

ラベルが異なる場合は、`Code.gs` 内の `pick_()` 呼び出しのキーを更新してください。

`申請理由・利用目的` は承認判断の必須情報として扱われ、未入力の場合は受け付けられません。

## 5. Gemini提案アシスタント（申請前支援）

申請者がIAMロール名を知らなくても、「Google Cloudでやりたいこと」から候補ロールを事前に確認できます。

1. Apps Script に `GeminiRoleAdvisor.gs` と `RoleAdvisor.html` を配置します。
1. **[重要] マニフェストファイルの修正**: GASエディタの「プロジェクト設定」で「`appsscript.json` マニフェスト ファイルをエディタで表示する」にチェックを入れます。エディタに表示された `appsscript.json` を開き、以下の `oauthScopes` を追加して保存してください。
   ```json
   {
     "oauthScopes": [
       "https://www.googleapis.com/auth/script.external_request",
       "https://www.googleapis.com/auth/cloud-platform"
     ]
   }
   ```
1. **[重要] IAM権限の付与**: このWebアプリをデプロイするユーザー（あなた自身）に、GCPプロジェクト (`TOOL_PROJECT_ID`) に対する **「Vertex AI ユーザー (`roles/aiplatform.user`)」** ロールが付与されていることをGCPコンソールで確認してください。
1. Apps Script を Web アプリとしてデプロイします（実行ユーザー: 自分、アクセス: 組織内ユーザーまたは全員）。この際、権限の承認ダイアログが出たら許可してください。
1. 発行された Web アプリのURLを Googleフォームの説明文に貼り付けます。
1. 申請者は URL 先で提案を取得し、`付与・変更ロール` と `申請理由・利用目的` に転記してフォームを送信します。

注記:

- Googleフォーム本体に任意のJavaScriptの「ボタン」を直接埋め込むことはできません。運用上はフォーム説明欄のリンク導線で代替します。
- Geminiの提案は参考情報です。最終的な承認は管理者が行ってください。

## 6. トラブルシューティング

- `棚卸し` メニューが表示されない:

  - スプレッドシートを再読み込みしてください（`onOpen` は再読込時に実行されます）。
  - Apps Script の保存漏れがないか確認してください。
  - 初回はスクリプトの権限承認ダイアログが完了した後に再読み込みが必要です。

- Gemini提案アシスタントでエラーになる:

  - `GEMINI_API_KEY` がスクリプトプロパティに設定されているか確認してください。
  - Webアプリのデプロイ版が最新のコードになっているか確認してください（再デプロイ）。

- `マトリクス更新` 実行でエラーになる:

  - `IAM権限設定履歴` シート名が完全一致しているか確認してください。
  - ヘッダーに `リソース名 / リソースID / プリンシパル / 種別 / IAMロール / ステータス` があるか確認してください。

- トリガーが動かない:

  - インストール可能なトリガー（`onFormSubmit`, `onEdit`, 必要に応じて `refreshRequestReviewStatus_` の時間トリガー）が作成済みか確認してください。
  - `プロジェクト設定 > スクリプトプロパティ` の必須値（`BQ_PROJECT_ID`, `BQ_DATASET_ID`, `BQ_LOCATION`, `CLOUD_RUN_EXECUTE_URL`）を確認してください。

- BigQuery 関連の権限エラー:

  - Apps Script 側で `BigQuery API`（拡張サービス）が有効になっているか確認してください。
  - 紐づく GCP プロジェクトでも BigQuery API が有効か確認してください。

申し送り:

- 未テスト項目や検証結果は `docs/untested-items-handover.md` に記録してください。
