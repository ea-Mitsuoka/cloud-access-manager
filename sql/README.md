# SQL Execution Order (Workbook Format)

Run in this order:

1. `001_tables.sql` (core tables)
1. `004_workbook_tables.sql` (workbook-compatible master/history tables)
1. `002_views.sql` (core operational views)
1. `005_workbook_views.sql` (sheet-compatible views)
1. `007_seed_workbook_from_existing.sql` (optional seed from existing operational tables)
1. `003_reconciliation.sql` (reconciliation batch)

Notes:

- Replace `your_project.your_dataset` in each SQL file before execution.
- For matrix, use Spreadsheet pivot (`refreshIamMatrixPivotFromHistory()`), not SQL shaping.

Tip:

- If using root `saas.env`, run `bash scripts/sync-config.sh` and execute files under `build/sql/` instead.
