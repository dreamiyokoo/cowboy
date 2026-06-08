#!/usr/bin/env bash
# run.sh — USB 接続 Android からカウボーイゲームの結果を継続取得して API に送信する
#
# 使い方:
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh --once
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh --debug

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v adb &>/dev/null; then
    echo "[ERROR] adb が見つかりません。Android SDK (platform-tools) をインストールしてください。"
    exit 1
fi

DEVICES=$(adb devices | grep -c "device$" || true)
if [[ "$DEVICES" -eq 0 ]]; then
    echo "[ERROR] ADB デバイスが見つかりません。"
    echo "  1. Android の開発者オプション → USB デバッグ を ON にしてください。"
    echo "  2. USB を挿し直して 'このPCを信頼しますか？' を許可してください。"
    exit 1
fi
if [[ "$DEVICES" -gt 1 ]]; then
    echo "[ERROR] ADB デバイスが複数接続されています (${DEVICES}台)。"
    echo "  capture/config.yml の adb.device にシリアルを指定してください。"
    adb devices
    exit 1
fi

if [[ -z "${CAPTURE_USERNAME:-}" ]] || [[ -z "${CAPTURE_PASSWORD:-}" ]]; then
    echo "[ERROR] CAPTURE_USERNAME / CAPTURE_PASSWORD を環境変数で指定してください。"
    exit 1
fi

cd capture
exec python3 capture.py "$@"
