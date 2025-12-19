#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カメラ登録処理"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from collections.abc import AsyncIterator

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
import v1.fd_service_connect as fd_service_connect
import v1.fd_service_pb2 as fd_service_pb2
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
        "--fd-service-url",
        type=str,
        help="FDServiceのURL（PTZ制御ストリームを使用する場合）",
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

        # PTZ制御ストリーム処理（PTZサポートがある場合）
        if args.supports_ptz and args.fd_service_url:
            logger.info("PTZ制御ストリーム処理を開始します")
            await handle_ptz_stream(
                args.fd_service_url,
                camera_id,
                args.insecure,
                args.verbose,
            )
        elif args.supports_ptz and not args.fd_service_url:
            logger.warning("PTZサポートが有効ですが、--fd-service-urlが指定されていません。PTZ制御ストリームは開始されません。")

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


async def handle_ptz_stream(
    fd_service_url: str,
    camera_id: str,
    insecure: bool,
    verbose: bool,
) -> None:
    """PTZ制御ストリームを処理"""
    http_client: httpx.AsyncClient | None = None
    fd_client: fd_service_connect.FDServiceClient | None = None

    try:
        verify = not insecure
        http_client = httpx.AsyncClient(verify=verify)
        fd_client = fd_service_connect.FDServiceClient(
            fd_service_url,
            session=http_client,
        )

        logger.info(f"PTZ制御ストリームに接続: camera_id={camera_id}")

        # リクエスト送信用のキュー
        request_queue: asyncio.Queue[
            fd_service_pb2.StreamControlCommandsRequest | None
        ] = asyncio.Queue()

        async def request_iterator() -> AsyncIterator[fd_service_pb2.StreamControlCommandsRequest]:
            """ストリームリクエストイテレータ"""
            # 初期化メッセージを送信
            init_request = fd_service_pb2.StreamControlCommandsRequest()
            init_request.init.camera_id = camera_id
            yield init_request

            # キューからリクエストを送信
            while True:
                request = await request_queue.get()
                if request is None:
                    break
                yield request

        # ストリーム処理タスク
        async def process_responses():
            """レスポンスを処理し、必要に応じてリクエストをキューに追加"""
            try:
                async for response in fd_client.stream_control_commands(request_iterator()):
                    try:
                        # サーバーからコマンドを受信
                        if response.HasField("command"):
                            command = response.command
                            logger.info(
                                f"PTZ制御コマンドを受信: command_id={command.command_id}, "
                                f"type={command.type}, camera_id={command.camera_id}"
                            )

                            # PTZパラメータが設定されている場合
                            if command.HasField("ptz_parameters"):
                                ptz = command.ptz_parameters
                                logger.info(
                                    f"PTZパラメータ: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}, "
                                    f"pan_speed={ptz.pan_speed}, tilt_speed={ptz.tilt_speed}, "
                                    f"zoom_speed={ptz.zoom_speed}"
                                )

                            # 実際のカメラにPTZコマンドを適用
                            result = await execute_ptz_command(command, verbose)

                            # 結果をストリームに送信
                            result_request = fd_service_pb2.StreamControlCommandsRequest()
                            result_request.result.CopyFrom(result)
                            await request_queue.put(result_request)

                            logger.info(
                                f"PTZコマンド実行完了: command_id={command.command_id}, "
                                f"success={result.success}"
                            )

                        # ステータスメッセージを受信
                        elif response.HasField("status"):
                            status = response.status
                            logger.info(
                                f"ストリームステータス: connected={status.connected}, "
                                f"message={status.message}"
                            )

                    except Exception as e:
                        logger.error(f"PTZストリーム処理エラー: {e}", exc_info=verbose)
            except Exception as e:
                logger.error(f"PTZストリーム受信エラー: {e}", exc_info=verbose)
            finally:
                # ストリーム終了を通知
                await request_queue.put(None)

        # ストリーム処理を開始
        await process_responses()

    except ConnectError as e:
        logger.error(f"PTZストリーム接続エラー: {e}", exc_info=verbose)
    except Exception as e:
        logger.error(f"PTZストリーム処理エラー: {e}", exc_info=verbose)
    finally:
        if http_client:
            await http_client.aclose()
        logger.info("PTZ制御ストリーム処理を終了します")


async def execute_ptz_command(
    command: fd_service_pb2.ControlCommand,
    verbose: bool,
) -> fd_service_pb2.ControlCommandResult:
    """PTZコマンドを実行"""
    result = fd_service_pb2.ControlCommandResult()
    result.command_id = command.command_id
    result.success = True

    try:
        # TODO: 実際のカメラ制御APIを呼び出す
        # 現在はログ出力のみ
        command_type_name = fd_service_pb2.ControlCommandType.Name(command.type)
        logger.info(f"PTZコマンド実行: type={command_type_name}")

        if command.HasField("ptz_parameters"):
            ptz = command.ptz_parameters
            logger.info(
                f"PTZパラメータ適用: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}"
            )
            # 実際のPTZパラメータを設定
            result.resulting_ptz.CopyFrom(ptz)

        result.execution_time_ms = 100  # 仮の実行時間

    except Exception as e:
        logger.error(f"PTZコマンド実行エラー: {e}", exc_info=verbose)
        result.success = False
        result.error_message = str(e)

    return result


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
