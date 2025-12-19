#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from threading import Thread
from dataclasses import dataclass
from typing import Any

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

import v1.ptz_service_connect as ptz_service_connect
import v1.ptz_service_pb2 as ptz_service_pb2
import v1.cr_service_pb2 as cr_service_pb2
import v1.cinematography_pb2 as cinematography_pb2

logger = logging.getLogger(__name__)

_servo_controller: "ServoController | None" = None
_last_ptz: "cinematography_pb2.PTZParameters | None" = None
_gui_server: "HTTPServer | None" = None
_executing_task_id: str = ""
_completed_task_id: str = ""
_device_status: "ptz_service_pb2.DeviceStatus.ValueType" = (
    ptz_service_pb2.DeviceStatus.DEVICE_STATUS_IDLE
)
_interrupt_requested: bool = False

PTZ_POLL_INTERVAL_SEC = 0.5


@dataclass
class PTZCorrection:
    """PTZ補正設定"""

    swap_pan_tilt: bool = False
    invert_pan: bool = False
    invert_tilt: bool = False


_ptz_correction: PTZCorrection = PTZCorrection()


def apply_ptz_correction(pan: float, tilt: float) -> tuple[float, float]:
    """PTZ補正を適用してパンとチルトの値を変換する"""
    corrected_pan = pan
    corrected_tilt = tilt

    if _ptz_correction.invert_pan:
        corrected_pan = -corrected_pan
    if _ptz_correction.invert_tilt:
        corrected_tilt = -corrected_tilt
    if _ptz_correction.swap_pan_tilt:
        corrected_pan, corrected_tilt = corrected_tilt, corrected_pan

    return corrected_pan, corrected_tilt


def set_ptz_correction(
    swap_pan_tilt: bool = False,
    invert_pan: bool = False,
    invert_tilt: bool = False,
) -> None:
    """PTZ補正設定を更新する"""
    global _ptz_correction
    _ptz_correction = PTZCorrection(
        swap_pan_tilt=swap_pan_tilt,
        invert_pan=invert_pan,
        invert_tilt=invert_tilt,
    )
    logger.info(
        f"PTZ補正設定を更新: swap_pan_tilt={swap_pan_tilt}, "
        f"invert_pan={invert_pan}, invert_tilt={invert_tilt}"
    )


class PTZGUIHandler(BaseHTTPRequestHandler):
    """PTZ状態を表示するGUI用HTTPハンドラー"""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/ptz/status":
            self._handle_status()
        elif self.path == "/" or self.path == "/index.html":
            self._handle_index()
        else:
            self.send_error(404, "Not Found")

    def _handle_status(self) -> None:
        """PTZ状態をJSONで返す"""
        global _last_ptz
        status = {
            "pan": _last_ptz.pan if _last_ptz else 0.0,
            "tilt": _last_ptz.tilt if _last_ptz else 0.0,
            "zoom": _last_ptz.zoom if _last_ptz else 0.0,
            "pan_speed": _last_ptz.pan_speed if _last_ptz else 0.0,
            "tilt_speed": _last_ptz.tilt_speed if _last_ptz else 0.0,
            "zoom_speed": _last_ptz.zoom_speed if _last_ptz else 0.0,
            "has_ptz": _last_ptz is not None,
        }
        response = json.dumps(status).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _handle_index(self) -> None:
        """PTZ状態表示用HTMLページを返す"""
        html = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>仮想PTZ状態表示</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 800px;
            width: 100%;
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
            text-align: center;
            font-size: 2em;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 2px solid #e9ecef;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .status-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }
        .status-label {
            font-size: 0.9em;
            color: #6c757d;
            margin-bottom: 10px;
            font-weight: 500;
        }
        .status-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }
        .visualization {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 30px;
            margin-top: 30px;
            text-align: center;
        }
        .camera-view {
            position: relative;
            width: 300px;
            height: 200px;
            margin: 20px auto;
            background: #e9ecef;
            border-radius: 12px;
            overflow: hidden;
        }
        .camera-indicator {
            position: absolute;
            width: 20px;
            height: 20px;
            background: #667eea;
            border-radius: 50%;
            border: 3px solid white;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
        }
        .zoom-indicator {
            margin-top: 20px;
            height: 30px;
            background: #e9ecef;
            border-radius: 15px;
            overflow: hidden;
            position: relative;
        }
        .zoom-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            border-radius: 15px;
        }
        .zoom-text {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-weight: bold;
            color: #333;
        }
        .no-data {
            color: #6c757d;
            font-style: italic;
            text-align: center;
            padding: 40px;
        }
        .last-update {
            text-align: center;
            color: #6c757d;
            font-size: 0.9em;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📹 仮想PTZ状態表示</h1>
        <div id="status-container">
            <div class="no-data">PTZデータを待機中...</div>
        </div>
        <div class="last-update" id="last-update"></div>
    </div>
    <script>
        function updateStatus() {
            fetch('/api/ptz/status')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('status-container');
                    const lastUpdate = document.getElementById('last-update');
                    
                    if (!data.has_ptz) {
                        container.innerHTML = '<div class="no-data">PTZデータがまだ受信されていません</div>';
                        lastUpdate.textContent = '';
                        return;
                    }
                    
                    const pan = data.pan.toFixed(2);
                    const tilt = data.tilt.toFixed(2);
                    const zoom = data.zoom.toFixed(2);
                    
                    // カメラの位置を計算（pan: -180~180 → 0~300, tilt: -90~90 → 0~200）
                    const panPos = ((data.pan + 180) / 360) * 300;
                    const tiltPos = ((data.tilt + 90) / 180) * 200;
                    
                    // ズームの割合（0~100として表示）
                    const zoomPercent = Math.max(0, Math.min(100, (data.zoom + 1) * 50));
                    
                    container.innerHTML = `
                        <div class="status-grid">
                            <div class="status-card">
                                <div class="status-label">Pan (水平)</div>
                                <div class="status-value">${pan}°</div>
                            </div>
                            <div class="status-card">
                                <div class="status-label">Tilt (垂直)</div>
                                <div class="status-value">${tilt}°</div>
                            </div>
                            <div class="status-card">
                                <div class="status-label">Zoom</div>
                                <div class="status-value">${zoom}</div>
                            </div>
                        </div>
                        <div class="visualization">
                            <h3 style="margin-bottom: 20px; color: #333;">カメラ視野</h3>
                            <div class="camera-view">
                                <div class="camera-indicator" style="left: ${panPos}px; top: ${tiltPos}px;"></div>
                            </div>
                            <div style="margin-top: 20px;">
                                <div style="margin-bottom: 10px; color: #333; font-weight: 500;">ズームレベル</div>
                                <div class="zoom-indicator">
                                    <div class="zoom-fill" style="width: ${zoomPercent}%;"></div>
                                    <div class="zoom-text">${zoomPercent.toFixed(1)}%</div>
                                </div>
                            </div>
                        </div>
                    `;
                    
                    lastUpdate.textContent = '最終更新: ' + new Date().toLocaleTimeString('ja-JP');
                })
                .catch(error => {
                    console.error('Error fetching PTZ status:', error);
                });
        }
        
        // 初回読み込み時と定期的に更新
        updateStatus();
        setInterval(updateStatus, 500);
    </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """マルチスレッド対応HTTPサーバー"""
    pass


def start_gui_server(port: int = 8888) -> None:
    """PTZ状態表示用GUIサーバーを起動"""
    global _gui_server
    if _gui_server is not None:
        logger.warning("GUIサーバーは既に起動しています")
        return

    def run_server() -> None:
        global _gui_server
        try:
            _gui_server = ThreadingHTTPServer(("127.0.0.1", port), PTZGUIHandler)
            logger.info(f"仮想PTZ GUIサーバーを起動しました: http://localhost:{port}")
            _gui_server.serve_forever()
        except Exception as e:
            logger.error(f"GUIサーバー起動エラー: {e}")

    thread = Thread(target=run_server, daemon=True)
    thread.start()


def stop_gui_server() -> None:
    """PTZ状態表示用GUIサーバーを停止"""
    global _gui_server
    if _gui_server is not None:
        _gui_server.shutdown()
        _gui_server = None
        logger.info("GUIサーバーを停止しました")


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


async def _polling_loop(
    ptz_client: ptz_service_connect.PTZServiceClient,
    camera_id: str,
    verbose: bool,
    virtual_ptz: bool = False,
) -> None:
    """PTZサービスへのポーリングループ（500ms間隔）"""
    global _executing_task_id, _completed_task_id, _device_status, _interrupt_requested

    logger.info("PTZポーリングループを開始します: camera_id=%s", camera_id)

    while True:
        try:
            request = ptz_service_pb2.PollingRequest()
            request.camera_id = camera_id
            request.device_status = _device_status
            request.camera_status = cr_service_pb2.CameraStatus.CAMERA_STATUS_ONLINE
            request.timestamp_ms = int(time.time() * 1000)

            if _completed_task_id:
                request.completed_task_id = _completed_task_id
            if _executing_task_id:
                request.executing_task_id = _executing_task_id
            if _last_ptz is not None:
                request.current_ptz.CopyFrom(_last_ptz)

            if verbose:
                logger.debug(
                    "ポーリングリクエスト送信: camera_id=%s, device_status=%s, "
                    "completed_task_id=%s, executing_task_id=%s",
                    camera_id,
                    ptz_service_pb2.DeviceStatus.Name(_device_status),
                    _completed_task_id,
                    _executing_task_id,
                )

            response = await ptz_client.polling(request)

            if verbose:
                logger.debug("ポーリングレスポンス(raw): %s", response)

            _completed_task_id = ""

            if response.interrupt:
                logger.info("中断フラグを受信しました - 現在のタスクを中断します")
                _interrupt_requested = True
                if _executing_task_id:
                    logger.info(
                        "実行中のタスクを中断: task_id=%s", _executing_task_id
                    )
                    _executing_task_id = ""
                    _device_status = ptz_service_pb2.DeviceStatus.DEVICE_STATUS_IDLE

            if response.HasField("current_command"):
                task = response.current_command
                if task.task_id and task.task_id != _executing_task_id:
                    logger.info(
                        "新しいタスクを受信: task_id=%s, layer=%s, status=%s",
                        task.task_id,
                        ptz_service_pb2.CommandLayer.Name(task.layer),
                        ptz_service_pb2.TaskStatus.Name(task.status),
                    )
                    _executing_task_id = task.task_id
                    _device_status = (
                        ptz_service_pb2.DeviceStatus.DEVICE_STATUS_EXECUTING
                    )

                    success = await execute_ptz_task(task, verbose, virtual_ptz)

                    if success:
                        logger.info("タスク完了: task_id=%s", task.task_id)
                        _completed_task_id = task.task_id
                    else:
                        logger.error("タスク失敗: task_id=%s", task.task_id)

                    _executing_task_id = ""
                    _device_status = ptz_service_pb2.DeviceStatus.DEVICE_STATUS_IDLE

            if response.HasField("next_command") and verbose:
                next_task = response.next_command
                logger.debug(
                    "次のタスク(プリフェッチ): task_id=%s, layer=%s",
                    next_task.task_id,
                    ptz_service_pb2.CommandLayer.Name(next_task.layer),
                )

        except ConnectError as e:
            logger.error("PTZポーリング接続エラー: %s", e, exc_info=verbose)
        except Exception as e:
            logger.error("PTZポーリング処理エラー: %s", e, exc_info=verbose)

        await asyncio.sleep(PTZ_POLL_INTERVAL_SEC)


async def handle_ptz_stream(
    ptz_service_url: str,
    camera_id: str,
    insecure: bool,
    verbose: bool,
    virtual_ptz: bool = False,
    gui_port: int | None = None,
    swap_pan_tilt: bool = False,
    invert_pan: bool = False,
    invert_tilt: bool = False,
) -> None:
    """PTZストリーム処理のエントリポイント"""
    http_client: httpx.AsyncClient | None = None
    ptz_client: ptz_service_connect.PTZServiceClient | None = None

    try:
        set_ptz_correction(
            swap_pan_tilt=swap_pan_tilt,
            invert_pan=invert_pan,
            invert_tilt=invert_tilt,
        )

        verify = not insecure
        http_client = httpx.AsyncClient(verify=verify)
        ptz_client = ptz_service_connect.PTZServiceClient(
            ptz_service_url,
            session=http_client,
        )

        if ptz_client is None:
            raise RuntimeError("PTZServiceClient is not initialized")

        mode_str = "仮想PTZモード" if virtual_ptz else "実機PTZモード"
        logger.info(
            "PTZ制御ストリーム処理を開始します: camera_id=%s, mode=%s",
            camera_id,
            mode_str,
        )

        if virtual_ptz and gui_port is not None:
            start_gui_server(gui_port)
            logger.info(
                f"仮想PTZ GUIをブラウザで開いてください: http://localhost:{gui_port}"
            )

        await _polling_loop(ptz_client, camera_id, verbose, virtual_ptz)

    except Exception as e:
        logger.error("PTZ制御ストリーム全体エラー: %s", e, exc_info=verbose)
    finally:
        if http_client:
            await http_client.aclose()
        stop_gui_server()
        logger.info("PTZ制御ストリーム処理を終了します")


async def execute_ptz_task(
    task: ptz_service_pb2.Task,
    verbose: bool,
    virtual_ptz: bool = False,
) -> bool:
    """PTZタスクを実行する"""
    global _last_ptz, _interrupt_requested

    try:
        if task.HasField("ptz_command"):
            ptz_cmd = task.ptz_command
            op_type = ptz_cmd.operation_type
            op_type_name = ptz_service_pb2.PTZOperationType.Name(op_type)
            logger.info(f"PTZコマンド実行: task_id={task.task_id}, type={op_type_name}")

            if op_type == ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_ABSOLUTE_MOVE:
                if ptz_cmd.HasField("absolute_move"):
                    await _execute_absolute_move(
                        ptz_cmd.absolute_move, verbose, virtual_ptz
                    )
            elif op_type == ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_RELATIVE_MOVE:
                if ptz_cmd.HasField("relative_move"):
                    await _execute_relative_move(
                        ptz_cmd.relative_move, verbose, virtual_ptz
                    )
            elif op_type == ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_CONTINUOUS_MOVE:
                if ptz_cmd.HasField("continuous_move"):
                    await _execute_continuous_move(
                        ptz_cmd.continuous_move, verbose, virtual_ptz
                    )

        elif task.HasField("cinematic_command"):
            logger.info(
                "シネマティックコマンドを受信: task_id=%s (未実装)",
                task.task_id,
            )

        return True

    except Exception as e:
        logger.error(f"PTZタスク実行エラー: {e}", exc_info=verbose)
        return False


async def _execute_absolute_move(
    cmd: ptz_service_pb2.AbsoluteMoveCommand,
    verbose: bool,
    virtual_ptz: bool,
) -> None:
    """AbsoluteMove命令を実行"""
    global _last_ptz

    pos = cmd.position
    speed = cmd.speed if cmd.HasField("speed") else None

    logger.info(
        f"AbsoluteMove実行: x={pos.x}, y={pos.y}, z={pos.z}"
        + (f", speed=({speed.pan_speed}, {speed.tilt_speed}, {speed.zoom_speed})"
           if speed else "")
    )

    ptz = cinematography_pb2.PTZParameters()
    pan = pos.x * 180.0
    tilt = pos.y * 90.0
    corrected_pan, corrected_tilt = apply_ptz_correction(pan, tilt)
    ptz.pan = corrected_pan
    ptz.tilt = corrected_tilt
    ptz.zoom = pos.z
    if speed:
        pan_speed = speed.pan_speed
        tilt_speed = speed.tilt_speed
        if _ptz_correction.swap_pan_tilt:
            pan_speed, tilt_speed = tilt_speed, pan_speed
        ptz.pan_speed = pan_speed
        ptz.tilt_speed = tilt_speed
        ptz.zoom_speed = speed.zoom_speed

    if virtual_ptz:
        logger.info(
            f"[仮想PTZ] AbsoluteMove: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}"
        )
    else:
        controller = get_servo_controller()
        if controller is not None:
            try:
                pan_angle = max(0, min(180, int(ptz.pan + 90)))
                tilt_angle = max(0, min(180, int(ptz.tilt + 90)))
                controller.move_both(pan_angle, tilt_angle)
                logger.info(f"PTZサーボ制御: pan={pan_angle}, tilt={tilt_angle}")
            except Exception as e:
                logger.error(f"PTZサーボ制御エラー: {e}", exc_info=verbose)

    _last_ptz = ptz


async def _execute_relative_move(
    cmd: ptz_service_pb2.RelativeMoveCommand,
    verbose: bool,
    virtual_ptz: bool,
) -> None:
    """RelativeMove命令を実行"""
    global _last_ptz

    trans = cmd.translation
    speed = cmd.speed if cmd.HasField("speed") else None

    logger.info(
        f"RelativeMove実行: pan_delta={trans.pan_delta}, "
        f"tilt_delta={trans.tilt_delta}, zoom_delta={trans.zoom_delta}"
    )

    ptz = cinematography_pb2.PTZParameters()
    if _last_ptz:
        ptz.CopyFrom(_last_ptz)

    pan_delta = trans.pan_delta
    tilt_delta = trans.tilt_delta
    if _ptz_correction.swap_pan_tilt:
        pan_delta, tilt_delta = tilt_delta, pan_delta
    if _ptz_correction.invert_pan:
        pan_delta = -pan_delta
    if _ptz_correction.invert_tilt:
        tilt_delta = -tilt_delta

    ptz.pan += pan_delta
    ptz.tilt += tilt_delta
    ptz.zoom += trans.zoom_delta

    if speed:
        pan_speed = speed.pan_speed
        tilt_speed = speed.tilt_speed
        if _ptz_correction.swap_pan_tilt:
            pan_speed, tilt_speed = tilt_speed, pan_speed
        ptz.pan_speed = pan_speed
        ptz.tilt_speed = tilt_speed
        ptz.zoom_speed = speed.zoom_speed

    if virtual_ptz:
        logger.info(
            f"[仮想PTZ] RelativeMove結果: pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}"
        )
    else:
        controller = get_servo_controller()
        if controller is not None:
            try:
                pan_angle = max(0, min(180, int(ptz.pan + 90)))
                tilt_angle = max(0, min(180, int(ptz.tilt + 90)))
                controller.move_both(pan_angle, tilt_angle)
                logger.info(f"PTZサーボ制御: pan={pan_angle}, tilt={tilt_angle}")
            except Exception as e:
                logger.error(f"PTZサーボ制御エラー: {e}", exc_info=verbose)

    _last_ptz = ptz


async def _execute_continuous_move(
    cmd: ptz_service_pb2.ContinuousMoveCommand,
    verbose: bool,
    virtual_ptz: bool,
) -> None:
    """ContinuousMove命令を実行（ジョイスティック用）"""
    global _last_ptz, _interrupt_requested

    vel = cmd.velocity
    timeout_ms = cmd.timeout_ms if cmd.timeout_ms > 0 else 500

    logger.info(
        f"ContinuousMove実行: pan_velocity={vel.pan_velocity}, "
        f"tilt_velocity={vel.tilt_velocity}, zoom_velocity={vel.zoom_velocity}, "
        f"timeout_ms={timeout_ms}"
    )

    ptz = cinematography_pb2.PTZParameters()
    if _last_ptz:
        ptz.CopyFrom(_last_ptz)

    pan_velocity = vel.pan_velocity
    tilt_velocity = vel.tilt_velocity
    if _ptz_correction.swap_pan_tilt:
        pan_velocity, tilt_velocity = tilt_velocity, pan_velocity
    if _ptz_correction.invert_pan:
        pan_velocity = -pan_velocity
    if _ptz_correction.invert_tilt:
        tilt_velocity = -tilt_velocity

    ptz.pan_speed = abs(pan_velocity)
    ptz.tilt_speed = abs(tilt_velocity)
    ptz.zoom_speed = abs(vel.zoom_velocity)

    start_time = time.time()
    step_interval = 0.05

    while (time.time() - start_time) * 1000 < timeout_ms:
        if _interrupt_requested:
            logger.info("ContinuousMove: 中断リクエストを受信しました")
            _interrupt_requested = False
            break

        ptz.pan += pan_velocity * step_interval * 10
        ptz.tilt += tilt_velocity * step_interval * 10
        ptz.zoom += vel.zoom_velocity * step_interval

        ptz.pan = max(-180.0, min(180.0, ptz.pan))
        ptz.tilt = max(-90.0, min(90.0, ptz.tilt))
        ptz.zoom = max(0.0, min(1.0, ptz.zoom))

        if virtual_ptz:
            if verbose:
                logger.debug(
                    f"[仮想PTZ] ContinuousMove: pan={ptz.pan:.2f}, "
                    f"tilt={ptz.tilt:.2f}, zoom={ptz.zoom:.2f}"
                )
        else:
            controller = get_servo_controller()
            if controller is not None:
                try:
                    pan_angle = max(0, min(180, int(ptz.pan + 90)))
                    tilt_angle = max(0, min(180, int(ptz.tilt + 90)))
                    controller.move_both(pan_angle, tilt_angle)
                except Exception as e:
                    logger.error(f"PTZサーボ制御エラー: {e}", exc_info=verbose)

        _last_ptz = ptz
        await asyncio.sleep(step_interval)

    logger.info(
        f"ContinuousMove完了: pan={ptz.pan:.2f}, tilt={ptz.tilt:.2f}, zoom={ptz.zoom:.2f}"
    )
