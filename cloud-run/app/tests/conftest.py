"""pytestの共通モック設定およびフィクスチャを提供するモジュール。"""

import os
from unittest.mock import patch, MagicMock

# 1. アプリケーションがインポートされる前に必須の環境変数をダミー値でセット
os.environ.setdefault("BQ_PROJECT_ID", "test-project-id")
os.environ.setdefault("BQ_DATASET_ID", "test_dataset")
os.environ.setdefault("MGMT_TARGET_PROJECT_ID", "test-target-project")
os.environ.setdefault("MGMT_TARGET_ORGANIZATION_ID", "")
os.environ.setdefault("WORKSPACE_CUSTOMER_ID", "my_customer")
os.environ.setdefault("EXECUTOR_IDENTITY", "test-executor")
os.environ.setdefault("GAS_INVOKER_EMAIL", "gas-invoker@example.com")
os.environ.setdefault("SCHEDULER_INVOKER_EMAIL", "scheduler@example.com")


# 2. pytestのコレクション（収集）段階でエラーになるのを防ぐため、
# Google Cloudのデフォルト認証(ADC)をグローバルにモック化する
mock_credentials = MagicMock()
auth_patcher = patch(
    "google.auth.default", return_value=(mock_credentials, "test-project-id")
)
auth_patcher.start()

# パッチを適用したままテストを実行できるようにするため、auth_patcherを停止しない

# app.main のインポートが必要な場合、この後に記述する。
# 例: from app.main import app
