# Cloud Access Manager ドキュメント

Cloud Access Managerは、Google Cloud環境におけるIAM権限の申請、承認、自動付与、監査、および定期棚卸しを一気通貫で管理するためのサーバーレスSaaS基盤です。

## 🚀 アーキテクチャ概要

システムは仮想マシンを一切持たず、Google Workspace（GAS Webアプリ/スプレッドシート）とGCPのフルマネージドサービス（Cloud Run/BigQuery）を組み合わせることで、「アイドル時の固定費ゼロ（Scale-to-Zero）」を実現しています。
（※アーキテクチャ図の詳細はリポジトリのREADMEをご参照ください）

## 📚 ドキュメントナビゲーション

上部のナビゲーションバー、または以下のリンクから各ドキュメントにアクセスしてください。

- **ユーザー・運用向け**
  - [ユーザーガイド (申請者向け)](operation/user-guide.md)
  - [運用マニュアル (SRE向け)](operation/operations-runbook.md)
  - [IAM権限の整合性管理とインシデント対応フロー](operation/iam-reconciliation-and-incident-flow.md)
- **設計・データ仕様**
  - [要件定義書](design/requirements.md)
  - [BigQuery テーブル仕様書](design/bigquery_tables.md)
  - [データリネージとマッピング](design/data_lineage_and_mapping.md)
- **開発・API**
  - [未検証項目引継ぎ](development/untested-items-handover.md)
  - [Python API リファレンス](api/main.md)
