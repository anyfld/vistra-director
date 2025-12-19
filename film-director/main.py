#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カメラ登録処理"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

import httpx

# gen/protoディレクトリをパスに追加（生成されたコードがv1.xxx形式でインポートするため）
project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(gen_proto_path))

# 生成されたコードはv1.xxx形式でインポートするため、gen/protoをパスに追加した後は直接v1からインポート
import v1.cd_service_connect as cd_service_connect
import v1.cd_service_pb2 as cd_service_pb2
import v1.cinematography_pb2 as cinematography_pb2
import v1.cr_service_pb2 as cr_service_pb2
from connectrpc.code import Code
from connectrpc.errors import ConnectError

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
    parser.add_argument(
        "--no-heartbeat",
        action="store_true",
        help="ハートビートを送信しない",
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


def build_register_request(args: argparse.Namespace) -> cd_service_pb2.RegisterCameraRequest:
    """カメラ登録リクエストを構築"""
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

    return request


async def do_register_camera(
    client: cd_service_connect.CameraServiceClient,
    request: cd_service_pb2.RegisterCameraRequest,
    verbose: bool,
) -> str:
    """カメラ登録を実行してカメラIDを返す"""
    logger.info(f"カメラ登録を開始: {request.name}")
    logger.debug(f"リクエスト: {request}")

    response = await client.register_camera(request)

    logger.info("カメラ登録が完了しました")
    logger.info(f"カメラID: {response.camera.id}")
    logger.info(f"カメラ名: {response.camera.name}")
    logger.info(f"モード: {response.camera.mode}")
    logger.info(f"ステータス: {response.camera.status}")
    logger.info(f"マスターフレームID: {response.camera.master_mf_id}")

    return response.camera.id


async def register_camera(args: argparse.Namespace) -> None:
    """カメラ登録処理"""
    request = build_register_request(args)

    # クライアントの作成とリクエスト送信
    camera_id: str | None = None
    http_client: httpx.AsyncClient | None = None
    client: cd_service_connect.CameraServiceClient | None = None

    try:
        verify = not args.insecure
        http_client = httpx.AsyncClient(verify=verify)
        client = cd_service_connect.CameraServiceClient(
            args.url,
            session=http_client,
        )

        camera_id = await do_register_camera(client, request, args.verbose)

        # ハートビート送信
        if not args.no_heartbeat:
            heartbeat_interval = 5.0
            logger.info(f"ハートビート送信を開始します（間隔: {heartbeat_interval}秒）")
            await send_heartbeats(
                client,
                camera_id,
                heartbeat_interval,
                args.verbose,
                args,
                request,
            )
        else:
            logger.info("ハートビート送信をスキップします")

    except KeyboardInterrupt:
        logger.info("処理が中断されました")
    except Exception as e:
        logger.error(f"カメラ登録に失敗しました: {e}", exc_info=args.verbose)
    finally:
        # 終了時にカメラ削除を送信
        if camera_id and client:
            try:
                await unregister_camera(client, camera_id, args.verbose)
            except Exception as e:
                logger.error(f"カメラ削除エラー: {e}", exc_info=args.verbose)
        # HTTPクライアントを閉じる
        if http_client:
            await http_client.aclose()


async def unregister_camera(
    client: cd_service_connect.CameraServiceClient,
    camera_id: str,
    verbose: bool,
) -> None:
    """カメラ削除処理"""
    try:
        logger.info(f"カメラ削除を開始: camera_id={camera_id}")
        request = cd_service_pb2.UnregisterCameraRequest()
        request.camera_id = camera_id

        response = await client.unregister_camera(request)

        if response.success:
            logger.info(f"カメラ削除が完了しました: camera_id={camera_id}")
        else:
            logger.warning(f"カメラ削除が失敗しました: camera_id={camera_id}")

    except Exception as e:
        logger.error(f"カメラ削除エラー: {e}", exc_info=verbose)


async def send_heartbeats(
    client: cd_service_connect.CameraServiceClient,
    camera_id: str,
    interval: float,
    verbose: bool,
    args: argparse.Namespace,
    register_request: cd_service_pb2.RegisterCameraRequest,
) -> None:
    """ハートビートを定期的に送信"""
    stop_event = asyncio.Event()
    current_camera_id = camera_id

    def signal_handler(signum: int, frame: object) -> None:
        logger.info("シグナルを受信しました。ハートビート送信を停止します...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while not stop_event.is_set():
            try:
                timestamp_ms = int(time.time() * 1000)

                heartbeat_request = cd_service_pb2.HeartbeatRequest()
                heartbeat_request.camera_id = current_camera_id
                heartbeat_request.timestamp_ms = timestamp_ms

                # PTZパラメータは現在のところ空（必要に応じて設定可能）
                # heartbeat_request.current_ptz.CopyFrom(...)

                # ステータスは現在のところ未指定（必要に応じて設定可能）
                # heartbeat_request.status = cr_service_pb2.CameraStatus.CAMERA_STATUS_ONLINE

                response = await client.heartbeat(heartbeat_request)

                if response.acknowledged:
                    logger.debug(
                        f"ハートビート送信成功: camera_id={current_camera_id}, "
                        f"server_timestamp_ms={response.server_timestamp_ms}"
                    )
                else:
                    logger.warning(
                        f"ハートビートが認識されませんでした: camera_id={current_camera_id}"
                    )

            except ConnectError as e:
                if e.code == Code.NOT_FOUND:
                    logger.warning(
                        f"カメラが見つかりませんでした（camera_id={current_camera_id}）。再登録を試みます..."
                    )
                    try:
                        new_camera_id = await do_register_camera(
                            client, register_request, verbose
                        )
                        current_camera_id = new_camera_id
                        logger.info(f"カメラ再登録が完了しました: camera_id={new_camera_id}")
                    except Exception as reg_error:
                        logger.error(
                            f"カメラ再登録に失敗しました: {reg_error}", exc_info=verbose
                        )
                else:
                    logger.error(f"ハートビート送信エラー: {e}", exc_info=verbose)
            except Exception as e:
                logger.error(f"ハートビート送信エラー: {e}", exc_info=verbose)

            # 次の送信まで待機
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    except KeyboardInterrupt:
        logger.info("ハートビート送信が中断されました")
    finally:
        logger.info("ハートビート送信を終了します")


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
