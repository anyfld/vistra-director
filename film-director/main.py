#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カメラ登録処理とWebRTC受信"""

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(gen_proto_path))

import httpx
import v1.cr_service_connect as cr_service_connect
import v1.cr_service_pb2 as cr_service_pb2
import v1.service_connect as service_connect
import v1.service_pb2 as service_pb2

from camera import register_camera
from webrtc_receiver import WebRTCReceiver

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
        required=False,
        help="カメラ名（カメラ登録時のみ必要）",
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
        required=False,
        help="マスターフレームID（カメラ登録時のみ必要）",
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
        "--ptz-service-url",
        type=str,
        default="http://localhost:8080",
        help="PTZServiceのURL（PTZ制御に使用, default: http://localhost:8080）",
    )
    parser.add_argument(
        "--virtual-ptz",
        action="store_true",
        help="仮想PTZモードを使用（ハードウェア制御を行わず、ログ出力のみ）",
    )
    parser.add_argument(
        "--virtual-ptz-gui-port",
        type=int,
        default=8888,
        help="仮想PTZ GUIサーバーのポート番号（default: 8888, 0で無効化）",
    )
    parser.add_argument(
        "--webrtc-connection-name",
        type=str,
        default="camera",
        help="WebRTC接続名 (default: camera)",
    )
    parser.add_argument(
        "--ptz-swap-pan-tilt",
        action="store_true",
        help="PTZ補正: パンとチルトを入れ替える",
    )
    parser.add_argument(
        "--ptz-invert-pan",
        action="store_true",
        help="PTZ補正: パンを反転する",
    )
    parser.add_argument(
        "--ptz-invert-tilt",
        action="store_true",
        help="PTZ補正: チルトを反転する",
    )
    parser.add_argument(
        "--cr-service-url",
        type=str,
        default="http://localhost:8080",
        help="CRServiceのURL（カメラ一覧取得に使用, default: http://localhost:8080）",
    )
    parser.add_argument(
        "--config-service-url",
        type=str,
        default="http://localhost:8080",
        help="ConfigServiceのURL（global config取得に使用, default: http://localhost:8080）",
    )
    parser.add_argument(
        "--receive-webrtc",
        action="store_true",
        help="カメラ一覧を取得してWebRTCを受信する",
    )
    return parser.parse_args()


async def get_global_config(
    config_service_url: str, insecure: bool, verbose: bool
) -> str:
    """Global config APIからWebRTCベースURLを取得"""
    logger.info("Global configを取得中...")
    verify = not insecure
    http_client = httpx.AsyncClient(verify=verify)
    try:
        client = service_connect.ConfigServiceClient(
            config_service_url,
            session=http_client,
        )
        request = service_pb2.GetGlobalConfigRequest()
        response = await client.get_global_config(request)
        webrtc_url = response.config.webrtc_url_template
        logger.info(f"WebRTCベースURLを取得: {webrtc_url}")
        return webrtc_url
    finally:
        await http_client.aclose()


async def list_cameras(
    cr_service_url: str, insecure: bool, verbose: bool
) -> list[cr_service_pb2.Camera]:
    """カメラ一覧を取得"""
    logger.info("カメラ一覧を取得中...")
    verify = not insecure
    http_client = httpx.AsyncClient(verify=verify)
    try:
        client = cr_service_connect.CRServiceClient(
            cr_service_url,
            session=http_client,
        )
        request = cr_service_pb2.ListAllCamerasRequest()
        response = await client.list_all_cameras(request)
        cameras = list(response.cameras)
        logger.info(f"カメラ一覧を取得: {len(cameras)}台")
        for camera in cameras:
            logger.info(
                f"  カメラID: {camera.id}, 名前: {camera.name}, "
                f"WebRTC接続名: {camera.webrtc_connection_name}"
            )
        return cameras
    finally:
        await http_client.aclose()


async def receive_webrtc_streams(args: argparse.Namespace) -> None:
    """カメラ一覧を取得してWebRTCストリームを受信"""
    http_client: httpx.AsyncClient | None = None
    receivers: list[WebRTCReceiver] = []

    try:
        # Global configからWebRTCベースURLを取得
        webrtc_url = await get_global_config(
            args.config_service_url, args.insecure, args.verbose
        )

        # カメラ一覧を取得
        cameras = await list_cameras(
            args.cr_service_url, args.insecure, args.verbose
        )

        if not cameras:
            logger.warning("カメラが見つかりませんでした")
            return

        # 各カメラのWebRTCストリームを受信
        for camera in cameras:
            if not camera.webrtc_connection_name:
                logger.warning(
                    f"カメラ {camera.id} ({camera.name}) にWebRTC接続名がありません"
                )
                continue

            logger.info(
                f"カメラ {camera.id} ({camera.name}) のWebRTCストリームを受信開始: "
                f"{camera.webrtc_connection_name}"
            )
            receiver = WebRTCReceiver(
                webrtc_url,
                camera.webrtc_connection_name,
                insecure=args.insecure,
            )
            receivers.append(receiver)
            try:
                await receiver.connect()
            except Exception as e:
                logger.error(
                    f"カメラ {camera.id} のWebRTC接続エラー: {e}",
                    exc_info=args.verbose,
                )

        if not receivers:
            logger.warning("接続できたカメラがありませんでした")
            return

        logger.info(f"{len(receivers)}台のカメラからWebRTCストリームを受信中...")
        logger.info("Ctrl+Cで終了します")

        # すべての受信を維持（Ctrl+Cで終了するまで待機）
        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("終了シグナルを受信しました")

    except KeyboardInterrupt:
        logger.info("処理が中断されました")
    except Exception as e:
        logger.error(f"WebRTC受信エラー: {e}", exc_info=args.verbose)
    finally:
        # すべての接続を切断
        for receiver in receivers:
            try:
                await receiver.disconnect()
            except Exception as e:
                logger.error(f"切断エラー: {e}", exc_info=args.verbose)
        if http_client:
            await http_client.aclose()


def main() -> None:
    """メイン関数"""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        if args.receive_webrtc:
            asyncio.run(receive_webrtc_streams(args))
        else:
            # カメラ登録モードでは必須パラメータをチェック
            if not args.name:
                logger.error("--name はカメラ登録時に必須です")
                sys.exit(1)
            if not args.master_mf_id:
                logger.error("--master-mf-id はカメラ登録時に必須です")
                sys.exit(1)
            asyncio.run(register_camera(args))
    except KeyboardInterrupt:
        logger.info("処理が中断されました")
    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
