#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from connectrpc.errors import ConnectError

project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(gen_proto_path))

try:
    from poc.cd.servo_controller import ServoController
except Exception:  # pragma: no cover
    ServoController = None  # type: ignore[assignment]

import v1.fd_service_connect as fd_service_connect
import v1.fd_service_pb2 as fd_service_pb2

logger = logging.getLogger(__name__)

_servo_controller: "ServoController | None"
_servo_controller = None


def get_servo_controller() -> "ServoController | None":
    global _servo_controller
    if ServoController is None:
        return None
    if _servo_controller is not None:
        return _servo_controller
    try:
        controller = ServoController()
        controller.connect()
    except Exception as e:
        logger.error(f"PTZハードウェア制御の初期化に失敗しました: {e}")
        return None
    _servo_controller = controller
    return _servo_controller


async def handle_ptz_stream(
    fd_service_url: str,
    camera_id: str,
    insecure: bool,
    verbose: bool,
) -> None:
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

        request_queue: asyncio.Queue[
            fd_service_pb2.StreamControlCommandsRequest | None
        ] = asyncio.Queue()

        async def request_iterator() -> AsyncIterator[fd_service_pb2.StreamControlCommandsRequest]:
            init_request = fd_service_pb2.StreamControlCommandsRequest()
            init_request.init.camera_id = camera_id
            yield init_request

            while True:
                request = await request_queue.get()
                if request is None:
                    break
                yield request

        async def process_responses():
            try:
                async for response in fd_client.stream_control_commands(request_iterator()):
                    try:
                        if response.HasField("command"):
                            command = response.command
                            logger.info(
                                f"PTZ制御コマンドを受信: command_id={command.command_id}, "
                                f"type={command.type}, camera_id={command.camera_id}"
                            )

                            if command.HasField("ptz_parameters"):
                                ptz = command.ptz_parameters
                                logger.info(
                                    f"PTZパラメータ: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}, "
                                    f"pan_speed={ptz.pan_speed}, tilt_speed={ptz.tilt_speed}, "
                                    f"zoom_speed={ptz.zoom_speed}"
                                )

                            result = await execute_ptz_command(command, verbose)

                            result_request = fd_service_pb2.StreamControlCommandsRequest()
                            result_request.result.CopyFrom(result)
                            await request_queue.put(result_request)

                            logger.info(
                                f"PTZコマンド実行完了: command_id={command.command_id}, "
                                f"success={result.success}"
                            )

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
                await request_queue.put(None)

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
    result = fd_service_pb2.ControlCommandResult()
    result.command_id = command.command_id
    result.success = True

    try:
        command_type_name = fd_service_pb2.ControlCommandType.Name(command.type)
        logger.info(f"PTZコマンド実行: type={command_type_name}")

        if command.HasField("ptz_parameters"):
            ptz = command.ptz_parameters
            logger.info(
                f"PTZパラメータ適用: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}"
            )

            controller = get_servo_controller()
            if controller is not None:
                try:
                    pan_angle = max(0, min(180, int(ptz.pan)))
                    tilt_angle = max(0, min(180, int(ptz.tilt)))
                    controller.move_both(pan_angle, tilt_angle)
                    logger.info(
                        f"PTZサーボ制御: pan={pan_angle}, tilt={tilt_angle}"
                    )
                except Exception as e:
                    logger.error(f"PTZサーボ制御エラー: {e}", exc_info=verbose)

            result.resulting_ptz.CopyFrom(ptz)

        result.execution_time_ms = 100

    except Exception as e:
        logger.error(f"PTZコマンド実行エラー: {e}", exc_info=verbose)
        result.success = False
        result.error_message = str(e)

    return result

