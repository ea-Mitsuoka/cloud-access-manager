#!/usr/bin/env bash
set -euo pipefail

# 旧スクリプト名を維持した後方互換ラッパー。
# 現在の正規コマンドは collect-principals.sh。
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT_DIR/scripts/collect-principals.sh" "$@"
