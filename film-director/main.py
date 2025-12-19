#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カメラ登録処理"""

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path

from camera import register_camera
from ptz import execute_ptz_command, handle_ptz_stream

logger = logging.getLogger(__name__)


def get_default_address() -> str:
    """ローカルIPアドレスを取得（失敗時は127.0.0.1）"""
    try:
        # 外部宛のダミー接続を使って、自分側のIPアドレスを取得
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def setup_logging(verbose: bool = False) -> None:
    """ログ設定"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数の解析"""
    parser = argparse.ArgumentParser(
        description="カメラ登録処理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8080",
        help="CameraServiceのURL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="カメラ名",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["AUTONOMOUS", "LIGHTWEIGHT"],
        default="AUTONOMOUS",
        help="カメラモード (default: AUTONOMOUS)",
    )
    parser.add_argument(
        "--master-mf-id",
        type=str,
        required=True,
        help="マスターフレームID",
    )
    parser.add_argument(
        "--connection-type",
        type=str,
        choices=["ONVIF", "NDI", "USB_SERIAL", "WEBRTC", "RTSP"],
        default="WEBRTC",
        help="接続タイプ (default: WEBRTC)",
    )
    parser.add_argument(
        "--address",
        type=str,
        default=get_default_address(),
        help="カメラのアドレス（IPアドレスまたはURL, default: ローカルIP）",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="カメラのポート番号",
    )
    parser.add_argument(
        "--username",
        type=str,
        help="認証ユーザー名",
    )
    parser.add_argument(
        "--password",
        type=str,
        help="認証パスワード",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="認証トークン",
    )
    parser.add_argument(
        "--supports-ptz",
        action="store_true",
        default=True,
        help="PTZサポート (default: 有効)",
    )
    parser.add_argument(
        "--no-ptz",
        dest="supports_ptz",
        action="store_false",
        help="PTZサポートを無効化",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        nargs="*",
        metavar="KEY=VALUE",
        help="メタデータ（KEY=VALUE形式で複数指定可能）",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="TLS証明書の検証をスキップ",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="詳細ログを出力",
    )
    parser.add_argument(
        "--fd-service-url",
        type=str,
        default="http://localhost:8080",
        help="FDServiceのURL（PTZ制御ストリームを使用する場合, default: http://localhost:8080）",
    )
    parser.add_argument(
        "--virtual-ptz",
        action="store_true",
        help="仮想PTZモードを使用（ハードウェア制御を行わず、ログ出力のみ）",
    )
    return parser.parse_args()


def main() -> None:
    """メイン関数"""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        asyncio.run(register_camera(args))
    except KeyboardInterrupt:
        logger.info("処理が中断されました")
    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
