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
from typing import Any, ClassVar

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
_gui_server: "HTTPServer | None" = None

PTZ_POLL_INTERVAL_SEC = 1.0
STATE_REPORT_INTERVAL_SEC = 5.0


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


async def _send_command_result(
    fd_client: fd_service_connect.FDServiceClient,
    result: fd_service_pb2.ControlCommandResult,
    verbose: bool,
) -> None:
    request = fd_service_pb2.StreamControlCommandsRequest()
    request.result.CopyFrom(result)
    if verbose:
        logger.debug(
            "PTZ制御結果を送信: command_id=%s, success=%s",
            result.command_id,
            result.success,
        )
    response = await fd_client.stream_control_commands(request)
    if response.HasField("status"):
        status = response.status
        logger.info(
            "PTZ制御結果送信ステータス: connected=%s, message=%s",
            status.connected,
            status.message,
        )
    if response.HasField("command") and verbose:
        command = response.command
        logger.debug(
            "結果送信レスポンスでPTZコマンドを受信: command_id=%s, type=%s, camera_id=%s",
            command.command_id,
            command.type,
            command.camera_id,
        )
    if response.HasField("result") and verbose:
        result_response = response.result
        logger.debug(
            "結果送信レスポンスで結果を受信: command_id=%s, success=%s",
            result_response.command_id,
            result_response.success,
        )


async def _poll_ptz_commands(
    fd_client: fd_service_connect.FDServiceClient,
    camera_id: str,
    verbose: bool,
    virtual_ptz: bool = False,
) -> None:
    logger.info("PTZ制御コマンド購読ループを開始します: camera_id=%s", camera_id)
    while True:
        try:
            request = fd_service_pb2.StreamControlCommandsRequest()
            init = request.init
            init.camera_id = camera_id
            if verbose:
                logger.debug(
                    "PTZ制御コマンド購読(init)リクエスト送信: camera_id=%s",
                    camera_id,
                )
            response = await fd_client.stream_control_commands(request)
            if verbose:
                logger.debug("PTZ制御レスポンス(raw): %s", response)
            if response.HasField("status"):
                status = response.status
                logger.info(
                    "PTZ制御ステータス: connected=%s, message=%s",
                    status.connected,
                    status.message,
                )
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
                result = await execute_ptz_command(command, verbose, virtual_ptz)
                logger.info(
                    "PTZコマンド実行完了: command_id=%s, success=%s",
                    result.command_id,
                    result.success,
                )
                await _send_command_result(fd_client, result, verbose)
            if response.HasField("result") and verbose:
                server_result = response.result
                logger.debug(
                    "PTZ制御結果レスポンスを受信: command_id=%s, success=%s",
                    server_result.command_id,
                    server_result.success,
                )
        except ConnectError as e:
            logger.error("PTZ制御コマンド購読接続エラー: %s", e, exc_info=verbose)
        except Exception as e:
            logger.error("PTZ制御コマンド購読処理エラー: %s", e, exc_info=verbose)
        await asyncio.sleep(PTZ_POLL_INTERVAL_SEC)


async def _send_camera_state_loop(
    fd_client: fd_service_connect.FDServiceClient,
    camera_id: str,
    verbose: bool,
) -> None:
    logger.info("PTZカメラ状態報告ループを開始します: camera_id=%s", camera_id)
    while True:
        try:
            request = fd_service_pb2.StreamControlCommandsRequest()
            state = request.state
            state.camera_id = camera_id
            state.updated_at_ms = int(time.time() * 1000)
            state.is_moving = False
            state.has_error = False
            if _last_ptz is not None:
                state.current_ptz.CopyFrom(_last_ptz)
            if verbose:
                logger.debug("PTZカメラ状態を送信: camera_id=%s", camera_id)
            response = await fd_client.stream_control_commands(request)
            if response.HasField("status"):
                status = response.status
                logger.info(
                    "PTZカメラ状態送信ステータス: connected=%s, message=%s",
                    status.connected,
                    status.message,
                )
            if response.HasField("command") and verbose:
                command = response.command
                logger.debug(
                    "状態報告レスポンスでPTZコマンドを受信(無視): "
                    "command_id=%s, type=%s, camera_id=%s",
                    command.command_id,
                    command.type,
                    command.camera_id,
                )
            if response.HasField("result") and verbose:
                result = response.result
                logger.debug(
                    "状態報告レスポンスで結果を受信(無視): command_id=%s, success=%s",
                    result.command_id,
                    result.success,
                )
        except ConnectError as e:
            logger.error("PTZカメラ状態報告接続エラー: %s", e, exc_info=verbose)
        except Exception as e:
            logger.error("PTZカメラ状態報告処理エラー: %s", e, exc_info=verbose)
        await asyncio.sleep(STATE_REPORT_INTERVAL_SEC)


async def handle_ptz_stream(
    fd_service_url: str,
    camera_id: str,
    insecure: bool,
    verbose: bool,
    virtual_ptz: bool = False,
    gui_port: int | None = None,
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
        if fd_client is None:
            raise RuntimeError("FDServiceClient is not initialized")
        mode_str = "仮想PTZモード" if virtual_ptz else "実機PTZモード"
        logger.info("PTZ制御ストリーム処理を開始します: camera_id=%s, mode=%s", camera_id, mode_str)
        
        if virtual_ptz and gui_port is not None:
            start_gui_server(gui_port)
            logger.info(f"仮想PTZ GUIをブラウザで開いてください: http://localhost:{gui_port}")
        
        await asyncio.gather(
            _poll_ptz_commands(fd_client, camera_id, verbose, virtual_ptz),
            _send_camera_state_loop(fd_client, camera_id, verbose),
        )
    except Exception as e:
        logger.error("PTZ制御ストリーム全体エラー: %s", e, exc_info=verbose)
    finally:
        if http_client:
            await http_client.aclose()
        stop_gui_server()
        logger.info("PTZ制御ストリーム処理を終了します")


async def execute_ptz_command(
    command: fd_service_pb2.ControlCommand,
    verbose: bool,
    virtual_ptz: bool = False,
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

            if virtual_ptz:
                logger.info(
                    "[仮想PTZ] ハードウェア制御をスキップ: "
                    f"pan={ptz.pan}, tilt={ptz.tilt}, zoom={ptz.zoom}"
                )
            else:
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
