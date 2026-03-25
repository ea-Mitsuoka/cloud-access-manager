# Apps Script Setup

## 1. Script properties

Set these values in `Project Settings > Script properties`.

- `BQ_PROJECT_ID`
- `BQ_DATASET_ID`
- `BQ_LOCATION` (optional, default: `asia-northeast1`)
- `CLOUD_RUN_EXECUTE_URL` (e.g. `https://<service-url>/execute`)
- `WEBHOOK_SHARED_SECRET` (optional but recommended)

## 2. Enable services

- `Services` -> add `BigQuery API` (Advanced Google Services)
- In linked Google Cloud project, also enable BigQuery API

## 3. Triggers

Create installable triggers:

- `onFormSubmit`: From spreadsheet, Event source `From spreadsheet`, Event type `On form submit`
- `onEdit`: From spreadsheet, Event source `From spreadsheet`, Event type `On edit`

## 4. Required form item labels

This script reads the following Japanese labels from form answers:

- `申請種別`
- `対象プリンシパル`
- `対象リソース`
- `付与・変更ロール`
- `申請理由・利用目的`
- `申請者メール`
- `承認者メール（または承認グループ）`

If your labels differ, update keys inside `pick_()` calls in `Code.gs`.
