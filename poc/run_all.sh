#!/bin/bash
#
# POC統合ランチャー（シェルスクリプト版）
# WebRTCMotionDetectionとObjectCropを同時に起動します
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# デフォルト設定
STARTUP_DELAY=3
INSECURE=""
INTERVAL="1.0"
KEEP_LATEST=""

# ヘルプ表示
show_help() {
    echo "使用方法: $0 [オプション]"
    echo ""
    echo "オプション:"
    echo "  -i, --insecure      SSL証明書の検証をスキップ"
    echo "  -d, --delay SEC     起動待機時間（デフォルト: 3秒）"
    echo "  -t, --interval SEC  クロップ間隔（デフォルト: 1.0秒）"
    echo "  -k, --keep-latest   最新画像のみ保持"
    echo "  -h, --help          このヘルプを表示"
    echo ""
    echo "例:"
    echo "  $0 --insecure"
    echo "  $0 --insecure --interval 2.0 --keep-latest"
}

# 引数解析
while [[ $# -gt 0 ]]; do
    case $1 in
        -i|--insecure)
            INSECURE="--insecure"
            shift
            ;;
        -d|--delay)
            STARTUP_DELAY="$2"
            shift 2
            ;;
        -t|--interval)
            INTERVAL="$2"
            shift 2
            ;;
        -k|--keep-latest)
            KEEP_LATEST="--keep-latest"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "不明なオプション: $1"
            show_help
            exit 1
            ;;
    esac
done

# クリーンアップ関数
cleanup() {
    echo ""
    echo "すべてのプロセスを停止中..."
    
    if [[ -n "$WEBRTC_PID" ]] && kill -0 "$WEBRTC_PID" 2>/dev/null; then
        kill "$WEBRTC_PID" 2>/dev/null || true
    fi
    
    if [[ -n "$CROP_PID" ]] && kill -0 "$CROP_PID" 2>/dev/null; then
        kill "$CROP_PID" 2>/dev/null || true
    fi
    
    wait 2>/dev/null || true
    echo "完了しました"
}

trap cleanup EXIT INT TERM

echo "============================================================"
echo "POC統合ランチャー"
echo "============================================================"
echo ""

# WebRTCMotionDetectionを起動
echo "[WebRTCMotionDetection] 起動中..."
cd "$SCRIPT_DIR/WebRTCMotionDetection"
uv run python main.py --share-frame $INSECURE &
WEBRTC_PID=$!
echo "[WebRTCMotionDetection] PID: $WEBRTC_PID"

# 起動待機
echo "[WebRTCMotionDetection] 起動待機中 (${STARTUP_DELAY}秒)..."
sleep "$STARTUP_DELAY"

# WebRTCMotionDetectionが起動しているか確認
if ! kill -0 "$WEBRTC_PID" 2>/dev/null; then
    echo "[エラー] WebRTCMotionDetectionの起動に失敗しました"
    exit 1
fi

# ObjectCropを起動
echo "[ObjectCrop] 起動中..."
cd "$SCRIPT_DIR/ObjectCrop"
uv run python main.py --interval "$INTERVAL" $KEEP_LATEST &
CROP_PID=$!
echo "[ObjectCrop] PID: $CROP_PID"

echo ""
echo "============================================================"
echo "すべてのプログラムが起動しました"
echo "終了するには Ctrl+C を押してください"
echo "============================================================"
echo ""

# プロセス監視
wait "$WEBRTC_PID"
echo "[WebRTCMotionDetection] が終了しました"
