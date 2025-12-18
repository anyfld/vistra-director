#!/usr/bin/env python3
"""
POC統合ランチャー

WebRTCMotionDetectionとObjectCropを同時に起動するスクリプトです。
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# スクリプトのディレクトリを取得
SCRIPT_DIR = Path(__file__).parent.absolute()


def run_all(args: argparse.Namespace) -> None:
    """すべてのプログラムを起動"""
    processes: list[subprocess.Popen] = []

    # シグナルハンドラを設定
    def signal_handler(signum, frame):
        print("\n終了シグナルを受信しました。すべてのプロセスを停止します...")
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 1. WebRTCMotionDetectionを起動
        webrtc_dir = SCRIPT_DIR / "WebRTCMotionDetection"
        webrtc_cmd = ["uv", "run", "python", "main.py", "--share-frame"]

        if args.url:
            webrtc_cmd.extend(["--url", args.url])
        if args.stream:
            webrtc_cmd.extend(["--stream", args.stream])
        if args.insecure:
            webrtc_cmd.append("--insecure")
        if args.model:
            webrtc_cmd.extend(["--model", args.model])
        if args.no_detection:
            webrtc_cmd.append("--no-detection")
        if args.no_motion:
            webrtc_cmd.append("--no-motion")
        if args.video_only:
            webrtc_cmd.append("--video-only")
        if args.confidence:
            webrtc_cmd.extend(["--confidence", str(args.confidence)])
        if args.imgsz:
            webrtc_cmd.extend(["--imgsz", str(args.imgsz)])
        if args.manual_crop_dir:
            webrtc_cmd.extend(["--manual-crop-dir", args.manual_crop_dir])
        if args.manual_crop_padding:
            webrtc_cmd.extend(["--manual-crop-padding", str(args.manual_crop_padding)])
        if args.manual_crop_label:
            webrtc_cmd.append("--manual-crop-label")
        if args.verbose:
            webrtc_cmd.append("--verbose")

        print(f"[WebRTCMotionDetection] 起動中...")
        print(f"  コマンド: {' '.join(webrtc_cmd)}")
        print(f"  ディレクトリ: {webrtc_dir}")

        webrtc_proc = subprocess.Popen(
            webrtc_cmd,
            cwd=webrtc_dir,
            env={**os.environ},
        )
        processes.append(webrtc_proc)

        # WebRTCMotionDetectionが起動するまで待機
        print(f"[WebRTCMotionDetection] 起動待機中 ({args.startup_delay}秒)...")
        time.sleep(args.startup_delay)

        # 2. ObjectCropを起動
        crop_dir = SCRIPT_DIR / "ObjectCrop"
        crop_cmd = ["uv", "run", "python", "main.py"]

        if args.output_dir:
            crop_cmd.extend(["--output-dir", args.output_dir])
        if args.classes:
            crop_cmd.extend(["--classes"] + args.classes)
        if args.padding:
            crop_cmd.extend(["--padding", str(args.padding)])
        if args.min_size:
            crop_cmd.extend(["--min-size", str(args.min_size)])
        if args.quality:
            crop_cmd.extend(["--quality", str(args.quality)])
        if args.format:
            crop_cmd.extend(["--format", args.format])
        if args.keep_latest:
            crop_cmd.append("--keep-latest")
        if args.max_images:
            crop_cmd.extend(["--max-images", str(args.max_images)])
        if args.iou_threshold:
            crop_cmd.extend(["--iou-threshold", str(args.iou_threshold)])
        if args.object_timeout:
            crop_cmd.extend(["--timeout", str(args.object_timeout)])
        if args.verbose:
            crop_cmd.append("--verbose")

        print(f"[ObjectCrop] 起動中...")
        print(f"  コマンド: {' '.join(crop_cmd)}")
        print(f"  ディレクトリ: {crop_dir}")

        crop_proc = subprocess.Popen(
            crop_cmd,
            cwd=crop_dir,
            env={**os.environ},
        )
        processes.append(crop_proc)

        print("\n" + "=" * 60)
        print("すべてのプログラムが起動しました")
        print("終了するには Ctrl+C を押すか、映像ウィンドウで 'q' キーを押してください")
        print("=" * 60 + "\n")

        # プロセスの監視
        while True:
            # WebRTCMotionDetectionが終了したらすべて終了
            if webrtc_proc.poll() is not None:
                print("\n[WebRTCMotionDetection] が終了しました")
                break

            # ObjectCropが終了しても続行（再接続を試みる可能性あり）
            if crop_proc.poll() is not None:
                print("\n[ObjectCrop] が終了しました")
                # 再起動するかどうかはオプションで制御可能
                break

            time.sleep(0.5)

    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
    finally:
        # すべてのプロセスを終了
        print("\nすべてのプロセスを停止中...")
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        print("完了しました")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="POC統合ランチャー - WebRTCMotionDetectionとObjectCropを同時起動",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使用（デフォルト設定）
  python run_all.py --insecure

  # カスタム設定で起動
  python run_all.py --insecure --url https://192.168.1.100 --interval 2.0 --keep-latest

  # 映像のみ（検知なし）でクロップ
  python run_all.py --insecure --video-only --interval 0.5
        """,
    )

    # WebRTCMotionDetection用オプション
    webrtc_group = parser.add_argument_group("WebRTCMotionDetection オプション")
    webrtc_group.add_argument(
        "--url",
        type=str,
        default="https://172.20.10.3",
        help="go2rtcサーバーのベースURL（デフォルト: https://172.20.10.3）",
    )
    webrtc_group.add_argument(
        "--stream",
        type=str,
        default="camera",
        help="go2rtcのストリーム名（デフォルト: camera）",
    )
    webrtc_group.add_argument(
        "--insecure",
        action="store_true",
        help="SSL証明書の検証をスキップする（自己署名証明書用）",
    )
    webrtc_group.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="YOLOv8モデル（デフォルト: yolov8n.pt）",
    )
    webrtc_group.add_argument(
        "--no-detection",
        action="store_true",
        help="物体検知（YOLO）を無効にする",
    )
    webrtc_group.add_argument(
        "--no-motion",
        action="store_true",
        help="動体検知を無効にする",
    )
    webrtc_group.add_argument(
        "--video-only",
        action="store_true",
        help="映像のみ表示（物体検知・動体検知を両方無効）",
    )
    webrtc_group.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="物体検知の信頼度閾値（デフォルト: 0.5）",
    )
    webrtc_group.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="YOLO推論画像サイズ（デフォルト: 640）",
    )
    webrtc_group.add_argument(
        "--manual-crop-dir",
        type=str,
        default="manual_crops",
        help="手動クロップの出力ディレクトリ（デフォルト: manual_crops）",
    )
    webrtc_group.add_argument(
        "--manual-crop-padding",
        type=int,
        default=10,
        help="手動クロップ時の余白ピクセル（デフォルト: 10）",
    )
    webrtc_group.add_argument(
        "--manual-crop-label",
        action="store_true",
        help="手動クロップ画像にラベル（連番-オブジェクト名）を追加する",
    )

    # ObjectCrop用オプション
    crop_group = parser.add_argument_group("ObjectCrop オプション")
    crop_group.add_argument(
        "--output-dir",
        type=str,
        default="cropped_images",
        help="出力ディレクトリ（デフォルト: cropped_images）",
    )
    crop_group.add_argument(
        "--classes",
        type=str,
        nargs="+",
        default=None,
        help="クロップ対象のクラス名（例: --classes person tv）",
    )
    crop_group.add_argument(
        "--padding",
        type=int,
        default=10,
        help="クロップ時の余白ピクセル（デフォルト: 10）",
    )
    crop_group.add_argument(
        "--min-size",
        type=int,
        default=32,
        help="最小クロップサイズ（デフォルト: 32）",
    )
    crop_group.add_argument(
        "--quality",
        type=int,
        default=90,
        help="JPEG品質（デフォルト: 90）",
    )
    crop_group.add_argument(
        "--format",
        type=str,
        choices=["jpeg", "png"],
        default="jpeg",
        help="出力フォーマット（デフォルト: jpeg）",
    )
    crop_group.add_argument(
        "--keep-latest",
        action="store_true",
        help="クラスごとに最新の画像のみを保持する",
    )
    crop_group.add_argument(
        "--max-images",
        type=int,
        default=100,
        help="保持する最大画像数（デフォルト: 100）",
    )
    crop_group.add_argument(
        "--iou-threshold",
        type=float,
        default=0.3,
        help="同一オブジェクトと判定するIoU閾値（デフォルト: 0.3）",
    )
    crop_group.add_argument(
        "--object-timeout",
        type=float,
        default=2.0,
        help="オブジェクトが消えたと判定する時間（秒、デフォルト: 2.0）",
    )

    # 共通オプション
    common_group = parser.add_argument_group("共通オプション")
    common_group.add_argument(
        "--startup-delay",
        type=float,
        default=3.0,
        help="WebRTCMotionDetection起動後の待機時間（秒、デフォルト: 3.0）",
    )
    common_group.add_argument(
        "--verbose",
        action="store_true",
        help="詳細なログを出力する",
    )

    args = parser.parse_args()
    run_all(args)


if __name__ == "__main__":
    main()
