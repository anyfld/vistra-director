#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import logging
import sys
from pathlib import Path

import httpx

project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(gen_proto_path))

import v1.cd_service_connect as cd_service_connect
import v1.cd_service_pb2 as cd_service_pb2
import v1.cr_service_pb2 as cr_service_pb2

from ptz import handle_ptz_stream

logger = logging.getLogger(__name__)


def parse_metadata(metadata_list: list[str] | None) -> dict[str, str]:
    if not metadata_list:
        return {}
    result = {}
    for item in metadata_list:
        if "=" not in item:
            logger.warning(
                f"無効なメタデータ形式: {item} (KEY=VALUE形式で指定してください)"
            )
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def build_register_request(args: argparse.Namespace) -> cd_service_pb2.RegisterCameraRequest:
    camera_mode_map = {
        "AUTONOMOUS": cr_service_pb2.CameraMode.CAMERA_MODE_AUTONOMOUS,
        "LIGHTWEIGHT": cr_service_pb2.CameraMode.CAMERA_MODE_LIGHTWEIGHT,
    }
    camera_mode = camera_mode_map[args.mode]

    connection_type_map = {
        "ONVIF": cd_service_pb2.ConnectionType.CONNECTION_TYPE_ONVIF,
        "NDI": cd_service_pb2.ConnectionType.CONNECTION_TYPE_NDI,
        "USB_SERIAL": cd_service_pb2.ConnectionType.CONNECTION_TYPE_USB_SERIAL,
        "WEBRTC": cd_service_pb2.ConnectionType.CONNECTION_TYPE_WEBRTC,
        "RTSP": cd_service_pb2.ConnectionType.CONNECTION_TYPE_RTSP,
    }
    connection_type = connection_type_map[args.connection_type]

    connection = cd_service_pb2.CameraConnection()
    connection.type = connection_type
    connection.address = args.address
    if args.port:
        connection.port = args.port

    if args.username or args.password or args.token:
        credentials = cd_service_pb2.CameraCredentials()
        if args.username:
            credentials.username = args.username
        if args.password:
            credentials.password = args.password
        if args.token:
            credentials.token = args.token
        connection.credentials.CopyFrom(credentials)

    capabilities = cd_service_pb2.CameraCapabilities()
    capabilities.supports_ptz = args.supports_ptz

    request = cd_service_pb2.RegisterCameraRequest()
    request.name = args.name
    request.mode = camera_mode
    request.master_mf_id = args.master_mf_id
    request.connection.CopyFrom(connection)
    request.capabilities.CopyFrom(capabilities)

    metadata = parse_metadata(args.metadata)
    for key, value in metadata.items():
        request.metadata[key] = value

    return request


async def do_register_camera(
    client: cd_service_connect.CameraServiceClient,
    request: cd_service_pb2.RegisterCameraRequest,
    verbose: bool,
) -> str:
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


async def unregister_camera(
    client: cd_service_connect.CameraServiceClient,
    camera_id: str,
    verbose: bool,
) -> None:
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


async def register_camera(args: argparse.Namespace) -> None:
    request = build_register_request(args)

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

        if args.supports_ptz and args.fd_service_url:
            logger.info("PTZ制御ストリーム処理を開始します")
            await handle_ptz_stream(
                args.fd_service_url,
                camera_id,
                args.insecure,
                args.verbose,
                getattr(args, "virtual_ptz", False),
            )
        elif args.supports_ptz and not args.fd_service_url:
            logger.warning(
                "PTZサポートが有効ですが、--fd-service-urlが指定されていません。PTZ制御ストリームは開始されません。"
            )

    except KeyboardInterrupt:
        logger.info("処理が中断されました")
    except Exception as e:
        logger.error(f"カメラ登録に失敗しました: {e}", exc_info=args.verbose)
    finally:
        if camera_id and client:
            try:
                await unregister_camera(client, camera_id, args.verbose)
            except Exception as e:
                logger.error(f"カメラ削除エラー: {e}", exc_info=args.verbose)
        if http_client:
            await http_client.aclose()
