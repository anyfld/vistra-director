#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""film-directorのテスト"""

import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# gen/protoディレクトリをパスに追加
project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(gen_proto_path))

import v1.cinematography_pb2 as cinematography_pb2
import v1.fd_service_pb2 as fd_service_pb2
from ptz import execute_ptz_command, handle_ptz_stream


@pytest.mark.asyncio
async def test_execute_ptz_command_success():
    """PTZコマンド実行の成功テスト"""
    command = fd_service_pb2.ControlCommand()
    command.command_id = "test-command-1"
    command.camera_id = "camera-1"
    command.type = fd_service_pb2.ControlCommandType.CONTROL_COMMAND_TYPE_PTZ_ABSOLUTE

    ptz = cinematography_pb2.PTZParameters()
    ptz.pan = 10.0
    ptz.tilt = 20.0
    ptz.zoom = 1.5
    command.ptz_parameters.CopyFrom(ptz)

    result = await execute_ptz_command(command, verbose=False)

    assert result.command_id == "test-command-1"
    assert result.success is True
    assert result.HasField("resulting_ptz")
    assert result.resulting_ptz.pan == 10.0
    assert result.resulting_ptz.tilt == 20.0
    assert result.resulting_ptz.zoom == 1.5
    assert result.execution_time_ms > 0


@pytest.mark.asyncio
async def test_execute_ptz_command_without_ptz_parameters():
    """PTZパラメータなしのコマンド実行テスト"""
    command = fd_service_pb2.ControlCommand()
    command.command_id = "test-command-2"
    command.camera_id = "camera-1"
    command.type = fd_service_pb2.ControlCommandType.CONTROL_COMMAND_TYPE_PTZ_STOP

    result = await execute_ptz_command(command, verbose=False)

    assert result.command_id == "test-command-2"
    assert result.success is True
    assert result.execution_time_ms > 0


@pytest.mark.asyncio
async def test_execute_ptz_command_relative():
    """相対PTZコマンドのテスト"""
    command = fd_service_pb2.ControlCommand()
    command.command_id = "test-command-3"
    command.camera_id = "camera-1"
    command.type = fd_service_pb2.ControlCommandType.CONTROL_COMMAND_TYPE_PTZ_RELATIVE

    ptz = cinematography_pb2.PTZParameters()
    ptz.pan_speed = 0.5
    ptz.tilt_speed = -0.3
    ptz.zoom_speed = 0.2
    command.ptz_parameters.CopyFrom(ptz)

    result = await execute_ptz_command(command, verbose=False)

    assert result.command_id == "test-command-3"
    assert result.success is True
    assert result.HasField("resulting_ptz")


@pytest.mark.asyncio
async def test_handle_ptz_stream_initialization():
    """PTZストリーム処理の初期化テスト"""
    camera_id = "test-camera-1"
    fd_service_url = "http://localhost:8081"

    # モックのレスポンスを作成（単一レスポンスのunary RPCに合わせる）
    init_response = fd_service_pb2.StreamControlCommandsResponse()
    init_response.status.connected = True
    init_response.status.message = "Connected"
    init_response.timestamp_ms = 1000

    command_response = fd_service_pb2.StreamControlCommandsResponse()
    command_response.command.command_id = "cmd-1"
    command_response.command.camera_id = camera_id
    command_response.command.type = (
        fd_service_pb2.ControlCommandType.CONTROL_COMMAND_TYPE_PTZ_ABSOLUTE
    )
    ptz = cinematography_pb2.PTZParameters()
    ptz.pan = 5.0
    ptz.tilt = 10.0
    ptz.zoom = 2.0
    command_response.command.ptz_parameters.CopyFrom(ptz)
    command_response.timestamp_ms = 2000

    with patch("ptz.fd_service_connect.FDServiceClient") as mock_client_class:
        mock_client = MagicMock()
        # 最初の呼び出しでステータス、次の呼び出しでコマンドを返す
        mock_client.stream_control_commands = AsyncMock(
            side_effect=[init_response, command_response]
        )
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            # ストリーム処理を実行（タイムアウトを設定）
            try:
                await asyncio.wait_for(
                    handle_ptz_stream(fd_service_url, camera_id, False, False),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                pass  # ストリームが継続するため、タイムアウトは想定内

            # クライアントが作成されたことを確認
            mock_client_class.assert_called_once()
            mock_http_client_class.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ptz_stream_command_processing():
    """PTZストリームでのコマンド処理テスト"""
    camera_id = "test-camera-2"
    fd_service_url = "http://localhost:8081"

    # コマンドレスポンスを作成
    command_response = fd_service_pb2.StreamControlCommandsResponse()
    command_response.command.command_id = "cmd-2"
    command_response.command.camera_id = camera_id
    command_response.command.type = (
        fd_service_pb2.ControlCommandType.CONTROL_COMMAND_TYPE_PTZ_ABSOLUTE
    )
    ptz = cinematography_pb2.PTZParameters()
    ptz.pan = 15.0
    ptz.tilt = 25.0
    ptz.zoom = 3.0
    command_response.command.ptz_parameters.CopyFrom(ptz)
    command_response.timestamp_ms = 3000

    with patch("ptz.fd_service_connect.FDServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream_control_commands = AsyncMock(return_value=command_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(fd_service_url, camera_id, False, False),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                pass

            # ストリームが呼び出されたことを確認
            mock_client.stream_control_commands.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ptz_stream_connection_error():
    """PTZストリーム接続エラーのテスト"""
    camera_id = "test-camera-3"
    fd_service_url = "http://localhost:8081"

    from connectrpc.errors import ConnectError
    from connectrpc.code import Code

    with patch("ptz.fd_service_connect.FDServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream_control_commands = AsyncMock(
            side_effect=ConnectError(Code.UNAVAILABLE, "Connection failed")
        )
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            await handle_ptz_stream(fd_service_url, camera_id, False, False)

            mock_http_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ptz_stream_status_message():
    """PTZストリームでのステータスメッセージ処理テスト"""
    camera_id = "test-camera-4"
    fd_service_url = "http://localhost:8081"

    status_response = fd_service_pb2.StreamControlCommandsResponse()
    status_response.status.connected = True
    status_response.status.message = "Stream active"
    status_response.timestamp_ms = 4000

    with patch("ptz.fd_service_connect.FDServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream_control_commands = AsyncMock(return_value=status_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(fd_service_url, camera_id, False, False),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                pass

            # ストリームが呼び出されたことを確認
            mock_client.stream_control_commands.assert_called_once()
