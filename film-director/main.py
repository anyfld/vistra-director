#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カメラ登録処理"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from gen.proto.v1 import cd_service_connect, cd_service_pb2, cr_service_pb2

logger = logging.getLogger(__name__)


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
        required=True,
        help="カメラのアドレス（IPアドレスまたはURL）",
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
        help="PTZサポート",
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
    return parser.parse_args()


def parse_metadata(metadata_list: list[str] | None) -> dict[str, str]:
    """メタデータをパース"""
    if not metadata_list:
        return {}
    result = {}
    for item in metadata_list:
        if "=" not in item:
            logger.warning(f"無効なメタデータ形式: {item} (KEY=VALUE形式で指定してください)")
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


async def register_camera(args: argparse.Namespace) -> None:
    """カメラ登録処理"""
    # カメラモードの設定
    camera_mode_map = {
        "AUTONOMOUS": cr_service_pb2.CameraMode.CAMERA_MODE_AUTONOMOUS,
        "LIGHTWEIGHT": cr_service_pb2.CameraMode.CAMERA_MODE_LIGHTWEIGHT,
    }
    camera_mode = camera_mode_map[args.mode]

    # 接続タイプの設定
    connection_type_map = {
        "ONVIF": cd_service_pb2.ConnectionType.CONNECTION_TYPE_ONVIF,
        "NDI": cd_service_pb2.ConnectionType.CONNECTION_TYPE_NDI,
        "USB_SERIAL": cd_service_pb2.ConnectionType.CONNECTION_TYPE_USB_SERIAL,
        "WEBRTC": cd_service_pb2.ConnectionType.CONNECTION_TYPE_WEBRTC,
        "RTSP": cd_service_pb2.ConnectionType.CONNECTION_TYPE_RTSP,
    }
    connection_type = connection_type_map[args.connection_type]

    # CameraConnectionの構築
    connection = cd_service_pb2.CameraConnection()
    connection.type = connection_type
    connection.address = args.address
    if args.port:
        connection.port = args.port

    # 認証情報の設定
    if args.username or args.password or args.token:
        credentials = cd_service_pb2.CameraCredentials()
        if args.username:
            credentials.username = args.username
        if args.password:
            credentials.password = args.password
        if args.token:
            credentials.token = args.token
        connection.credentials.CopyFrom(credentials)

    # CameraCapabilitiesの構築
    capabilities = cd_service_pb2.CameraCapabilities()
    capabilities.supports_ptz = args.supports_ptz

    # RegisterCameraRequestの構築
    request = cd_service_pb2.RegisterCameraRequest()
    request.name = args.name
    request.mode = camera_mode
    request.master_mf_id = args.master_mf_id
    request.connection.CopyFrom(connection)
    request.capabilities.CopyFrom(capabilities)

    # メタデータの設定
    metadata = parse_metadata(args.metadata)
    for key, value in metadata.items():
        request.metadata[key] = value

    # クライアントの作成とリクエスト送信
    try:
        verify = not args.insecure
        async with httpx.AsyncClient(verify=verify) as http_client:
            client = cd_service_connect.CameraServiceClient(
                base_url=args.url,
                http_client=http_client,
            )

            logger.info(f"カメラ登録を開始: {args.name}")
            logger.debug(f"リクエスト: {request}")

            response = await client.register_camera(request)

        logger.info("カメラ登録が完了しました")
        logger.info(f"カメラID: {response.camera.id}")
        logger.info(f"カメラ名: {response.camera.name}")
        logger.info(f"モード: {response.camera.mode}")
        logger.info(f"ステータス: {response.camera.status}")
        logger.info(f"マスターフレームID: {response.camera.master_mf_id}")

    except Exception as e:
        logger.error(f"カメラ登録に失敗しました: {e}", exc_info=args.verbose)
        sys.exit(1)


def main() -> None:
    """メイン関数"""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        asyncio.run(register_camera(args))
    except KeyboardInterrupt:
        logger.info("処理が中断されました")
        sys.exit(1)
    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
