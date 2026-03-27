# SQL実行順序（ワークブック形式）

この順序で実行してください：

1. `001_tables.sql` (コアテーブル)
1. `004_workbook_tables.sql` (ワークブック互換のマスタ/履歴テーブル)
1. `002_views.sql` (コアオペレーショナルビュー)
1. `005_workbook_views.sql` (シート互換ビュー)
1. `007_seed_workbook_from_existing.sql` (既存のオペレーショナルテーブルからのオプショナルなシード)
1. `003_reconciliation.sql` (突合バッチ)

注意：

- 実行前に各SQLファイル内の `your_project.your_dataset` を置換してください。
- マトリクスについては、SQLでの整形ではなく、スプレッドシートのピボット (`refreshIamMatrixPivotFromHistory()`) を使用してください。

ヒント：

- ルートの `saas.env` を使用している場合は、`bash scripts/sync-config.sh` を実行し、代わりに `build/sql/` ディレクトリ配下のファイルを実行してください。
