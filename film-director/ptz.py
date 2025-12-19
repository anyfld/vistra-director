#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
import sys
import time
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

_servo_controller: "ServoController | None" = None
_last_ptz: "fd_service_pb2.PTZParameters | None" = None


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
        logger.error("PTZハードウェア制御の初期化に失敗しました: %s", e)
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
    last_result: fd_service_pb2.ControlCommandResult | None = None
    initialized = False

    try:
        verify = not insecure
        http_client = httpx.AsyncClient(verify=verify)
        fd_client = fd_service_connect.FDServiceClient(
            fd_service_url,
            session=http_client,
        )

        logger.info("PTZ制御ポーリングを開始します: camera_id=%s", camera_id)

        while True:
            try:
                request = fd_service_pb2.StreamControlCommandsRequest()

                if not initialized:
                    init = request.init
                    init.camera_id = camera_id
                    initialized = True
                    if verbose:
                        logger.debug("PTZ制御初期化リクエスト送信: camera_id=%s", camera_id)
                elif last_result is not None:
                    request.result.CopyFrom(last_result)
                    if verbose:
                        logger.debug(
                            "PTZ制御結果を送信: command_id=%s, success=%s",
                            last_result.command_id,
                            last_result.success,
                        )
                    last_result = None
                else:
                    state = request.state
                    state.camera_id = camera_id
                    state.updated_at_ms = int(time.time() * 1000)
                    state.is_moving = False
                    state.has_error = False
                    if _last_ptz is not None:
                        state.current_ptz.CopyFrom(_last_ptz)
                    if verbose:
                        logger.debug("PTZ制御状態を送信: camera_id=%s", camera_id)

                if fd_client is None:
                    raise RuntimeError("FDServiceClient is not initialized")

                response = await fd_client.stream_control_commands(request)

                if response.HasField("command"):
                    command = response.command
                    logger.info(
                        "PTZ制御コマンドを受信: command_id=%s, type=%s, camera_id=%s",
                        command.command_id,
                        command.type,
                        command.camera_id,
                    )

                    if command.HasField("ptz_parameters"):
                        ptz = command.ptz_parameters
                        logger.info(
                            "PTZパラメータ: pan=%s, tilt=%s, zoom=%s, "
                            "pan_speed=%s, tilt_speed=%s, zoom_speed=%s",
                            ptz.pan,
                            ptz.tilt,
                            ptz.zoom,
                            ptz.pan_speed,
                            ptz.tilt_speed,
                            ptz.zoom_speed,
                        )

                    last_result = await execute_ptz_command(command, verbose)

                    logger.info(
                        "PTZコマンド実行完了: command_id=%s, success=%s",
                        last_result.command_id,
                        last_result.success,
                    )

                elif response.HasField("status"):
                    status = response.status
                    logger.info(
                        "PTZ制御ステータス: connected=%s, message=%s",
                        status.connected,
                        status.message,
                    )

                elif response.HasField("result") and verbose:
                    result = response.result
                    logger.debug(
                        "PTZ制御結果レスポンスを受信: command_id=%s, success=%s",
                        result.command_id,
                        result.success,
                    )

            except ConnectError as e:
                logger.error("PTZ制御ポーリング接続エラー: %s", e, exc_info=verbose)
                time.sleep(2)
            except Exception as e:
                logger.error("PTZ制御ポーリング処理エラー: %s", e, exc_info=verbose)
                time.sleep(2)

            time.sleep(1)

    except Exception as e:
        logger.error("PTZ制御ポーリング全体エラー: %s", e, exc_info=verbose)
    finally:
        if http_client:
            await http_client.aclose()
        logger.info("PTZ制御ポーリング処理を終了します")


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
            global _last_ptz
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
            _last_ptz = ptz

        result.execution_time_ms = 100

    except Exception as e:
        logger.error(f"PTZコマンド実行エラー: {e}", exc_info=verbose)
        result.success = False
        result.error_message = str(e)

    return result

