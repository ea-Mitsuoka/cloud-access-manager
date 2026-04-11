# Cloud Access Manager 初期セットアップガイド（Google Workspace 連携）

Cloud Access Manager が貴社の組織（Google Workspace）に存在するユーザーやグループ、および Google Cloud 上のサービスアカウント情報を取得し、正確な「権限の棚卸しマスタ」を構築するための初期設定手順です。

本作業は、貴社の **Google Workspace 特権管理者** および **Google Cloud IAM 管理者** にて実施をお願いいたします。

## 📌 なぜこの設定が必要なのか？

当システムは、申請された権限と実際のアカウント状況を照合するため、以下の読み取り権限（Read-Only）のみを要求します。メールの閲覧や設定の変更権限は一切取得しません。

- **Google Workspace**: 組織内のユーザー一覧、グループ一覧、およびグループの所属メンバーの読み取り
- **Google Cloud**: プロジェクト内のサービスアカウント一覧の読み取り

※ Google Workspace の仕様上、システムアカウント（サービスアカウント）に直接管理者権限を付与することができないため、「セキュリティグループ」を中継する安全なベストプラクティス構成を採用しています。

______________________________________________________________________

## STEP 1: 権限付与用の「セキュリティグループ」を作成する

1. Google Workspace の [管理コンソール (Admin Console)](https://admin.google.com/) に特権管理者でログインします。
1. 左側メニューから **[ディレクトリ] > [グループ]** をクリックし、**[グループを作成]** を選択します。
1. グループの詳細を入力します。
   - グループ名: `Cloud Access Manager SA Group` (任意)
   - グループのメールアドレス: `cam-sa-group@貴社ドメイン` (任意)
   - ⚠️ **「セキュリティ」**: `セキュリティ グループ` のチェックボックスを `オン` にする
1. アクセス設定画面に進み、以下の2点を**必ず設定**してください。
   - ⚠️ **「外部のメンバーを許可する」**: `オン` にする（※システムアカウントを外部ユーザーとして追加するため）
1. グループを作成します。

## STEP 2: システムアカウントをグループのメンバーに追加する

1. 作成したグループの管理画面を開き、**[メンバーを追加]** をクリックします。
1. 以下の Cloud Access Manager 実行サービスアカウントのメールアドレスを入力し、メンバーとして追加します。
   - **サービスアカウント:** `iam-access-executor@<提供されたプロジェクトID>.iam.gserviceaccount.com`

## STEP 3: カスタム管理者ロールを作成し、割り当てる

1. 管理コンソールの左側メニューから **[アカウント] > [管理者ロール]** をクリックします。
1. **[新しいロールを作成]** をクリックし、名前（例: `Cloud Access Manager 読み取り専用ロール`）を入力して続行します。
1. 「権限を選択」の画面で、**[Admin API 権限]** のセクションを展開し、以下の **2つのみ** にチェックを入れます。
   - ☑️ **ユーザー > 読み取り**
   - ☑️ **グループ > 読み取り**
1. ロールを作成して保存します。
1. 作成したロールの画面で **[管理者を割り当て]** をクリックします。
1. 検索窓に、**STEP 1 で作成したグループのメールアドレス**（例: `cam-sa-group@...`）を入力して選択し、ロールを割り当てます。

> 💡 **確認:** これにより、システムアカウントがセキュリティグループ経由で安全に読み取り権限を継承する状態が完成します。

______________________________________________________________________

STEP 4: Google Cloud 側での権限付与
Cloud Access Manager が貴社の環境を管理できるよう、対象のスコープ（プロジェクト、フォルダ、または組織全体）に対して以下の3つのロールを付与してください。

1. Google Cloud Console にログインし、対象プロジェクトの **[IAM と管理] > [IAM]** を開きます。
1. **[アクセス権を付与]** をクリックします。
1. 「新しいプリンシパル」に、STEP 2 と同じサービスアカウントを入力します。
   - `iam-access-executor@<提供されたプロジェクトID>.iam.gserviceaccount.com`
1. 「ロールを選択」で以下のロールを割り当て、保存します。
   - **[Project IAM管理者]** (`roles/resourcemanager.projectIamAdmin`)
   - **[クラウドアセット閲覧者]** (`roles/cloudasset.viewer`)
   - **[サービス アカウント閲覧者]** (`roles/iam.serviceAccountViewer`)

[タブ1: gcloudコマンドを使用する場合] -> おすすめ1のスクリプトを記載

```bash
# 顧客のIT管理者にCloud Shellで実行してもらうコマンド
export TARGET_ORG_ID="顧客の組織ID (例: 123456789012)"
export SAAS_SA="iam-access-executor@<提供されたプロジェクトID>.iam.gserviceaccount.com"

# 組織配下の全プロジェクトのIAMを管理する権限
gcloud organizations add-iam-policy-binding $TARGET_ORG_ID \
    --member="serviceAccount:$SAAS_SA" \
    --role="roles/resourcemanager.projectIamAdmin"

# 組織配下の全リソース情報を収集する権限
gcloud organizations add-iam-policy-binding $TARGET_ORG_ID \
    --member="serviceAccount:$SAAS_SA" \
    --role="roles/cloudasset.viewer"

# 組織配下のサービスアカウント一覧を取得する権限
gcloud organizations add-iam-policy-binding $TARGET_ORG_ID \
    --member="serviceAccount:$SAAS_SA" \
    --role="roles/iam.serviceAccountViewer"
```

[タブ2: Terraformを使用する場合] -> おすすめ2のコードを記載

```bash
# Cloud Access Manager 連携用の権限付与
locals {
  cam_sa = "serviceAccount:iam-access-executor@<提供されたプロジェクトID>.iam.gserviceaccount.com"
}

resource "google_organization_iam_member" "cam_project_iam_admin" {
  org_id = var.organization_id
  role   = "roles/resourcemanager.projectIamAdmin"
  member = local.cam_sa
}

resource "google_organization_iam_member" "cam_asset_viewer" {
  org_id = var.organization_id
  role   = "roles/cloudasset.viewer"
  member = local.cam_sa
}

resource "google_organization_iam_member" "cam_sa_viewer" {
  org_id = var.organization_id
  role   = "roles/iam.serviceAccountViewer"
  member = local.cam_sa
}
```

以上で、すべての連携セットアップが完了です。
