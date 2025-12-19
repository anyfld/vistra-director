#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""film-directorのテスト"""

import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
gen_proto_path = project_root / "gen" / "proto"
sys.path.insert(0, str(gen_proto_path))

import v1.ptz_service_pb2 as ptz_service_pb2
from ptz import execute_ptz_task, handle_ptz_stream


@pytest.mark.asyncio
async def test_execute_ptz_task_absolute_move():
    """AbsoluteMove PTZタスク実行の成功テスト"""
    task = ptz_service_pb2.Task()
    task.task_id = "test-task-1"
    task.layer = ptz_service_pb2.CommandLayer.COMMAND_LAYER_PTZ
    task.status = ptz_service_pb2.TaskStatus.TASK_STATUS_EXECUTING

    ptz_cmd = task.ptz_command
    ptz_cmd.operation_type = (
        ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_ABSOLUTE_MOVE
    )
    ptz_cmd.absolute_move.position.x = 0.5
    ptz_cmd.absolute_move.position.y = -0.2
    ptz_cmd.absolute_move.position.z = 0.8
    ptz_cmd.absolute_move.speed.pan_speed = 1.0
    ptz_cmd.absolute_move.speed.tilt_speed = 1.0
    ptz_cmd.absolute_move.speed.zoom_speed = 0.5

    result = await execute_ptz_task(task, verbose=False, virtual_ptz=True)

    assert result is True


@pytest.mark.asyncio
async def test_execute_ptz_task_relative_move():
    """RelativeMove PTZタスク実行のテスト"""
    task = ptz_service_pb2.Task()
    task.task_id = "test-task-2"
    task.layer = ptz_service_pb2.CommandLayer.COMMAND_LAYER_PTZ
    task.status = ptz_service_pb2.TaskStatus.TASK_STATUS_EXECUTING

    ptz_cmd = task.ptz_command
    ptz_cmd.operation_type = (
        ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_RELATIVE_MOVE
    )
    ptz_cmd.relative_move.translation.pan_delta = 10.0
    ptz_cmd.relative_move.translation.tilt_delta = -5.0
    ptz_cmd.relative_move.translation.zoom_delta = 0.1

    result = await execute_ptz_task(task, verbose=False, virtual_ptz=True)

    assert result is True


@pytest.mark.asyncio
async def test_execute_ptz_task_continuous_move():
    """ContinuousMove PTZタスク実行のテスト"""
    task = ptz_service_pb2.Task()
    task.task_id = "test-task-3"
    task.layer = ptz_service_pb2.CommandLayer.COMMAND_LAYER_PTZ
    task.status = ptz_service_pb2.TaskStatus.TASK_STATUS_EXECUTING

    ptz_cmd = task.ptz_command
    ptz_cmd.operation_type = (
        ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_CONTINUOUS_MOVE
    )
    ptz_cmd.continuous_move.velocity.pan_velocity = 0.5
    ptz_cmd.continuous_move.velocity.tilt_velocity = 0.0
    ptz_cmd.continuous_move.velocity.zoom_velocity = 0.0
    ptz_cmd.continuous_move.timeout_ms = 100

    result = await execute_ptz_task(task, verbose=False, virtual_ptz=True)

    assert result is True


@pytest.mark.asyncio
async def test_execute_ptz_task_without_command():
    """コマンドなしのタスク実行テスト"""
    task = ptz_service_pb2.Task()
    task.task_id = "test-task-4"
    task.layer = ptz_service_pb2.CommandLayer.COMMAND_LAYER_CINEMATIC
    task.status = ptz_service_pb2.TaskStatus.TASK_STATUS_EXECUTING

    result = await execute_ptz_task(task, verbose=False, virtual_ptz=True)

    assert result is True


@pytest.mark.asyncio
async def test_handle_ptz_stream_initialization():
    """PTZストリーム処理の初期化テスト"""
    camera_id = "test-camera-1"
    ptz_service_url = "http://localhost:8081"

    polling_response = ptz_service_pb2.PollingResponse()
    polling_response.timestamp_ms = 1000

    with patch("ptz.ptz_service_connect.PTZServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.polling = AsyncMock(return_value=polling_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(ptz_service_url, camera_id, False, False),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

            mock_client_class.assert_called_once()
            mock_http_client_class.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ptz_stream_with_task():
    """PTZストリームでのタスク処理テスト"""
    camera_id = "test-camera-2"
    ptz_service_url = "http://localhost:8081"

    polling_response = ptz_service_pb2.PollingResponse()
    polling_response.timestamp_ms = 2000
    polling_response.current_command.task_id = "task-1"
    polling_response.current_command.layer = (
        ptz_service_pb2.CommandLayer.COMMAND_LAYER_PTZ
    )
    polling_response.current_command.status = (
        ptz_service_pb2.TaskStatus.TASK_STATUS_EXECUTING
    )
    polling_response.current_command.ptz_command.operation_type = (
        ptz_service_pb2.PTZOperationType.PTZ_OPERATION_TYPE_ABSOLUTE_MOVE
    )
    polling_response.current_command.ptz_command.absolute_move.position.x = 0.0
    polling_response.current_command.ptz_command.absolute_move.position.y = 0.0
    polling_response.current_command.ptz_command.absolute_move.position.z = 0.5

    with patch("ptz.ptz_service_connect.PTZServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.polling = AsyncMock(return_value=polling_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(
                        ptz_service_url, camera_id, False, False, virtual_ptz=True
                    ),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

            mock_client.polling.assert_called()


@pytest.mark.asyncio
async def test_handle_ptz_stream_connection_error():
    """PTZストリーム接続エラーのテスト"""
    camera_id = "test-camera-3"
    ptz_service_url = "http://localhost:8081"

    from connectrpc.errors import ConnectError
    from connectrpc.code import Code

    with patch("ptz.ptz_service_connect.PTZServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.polling = AsyncMock(
            side_effect=ConnectError(Code.UNAVAILABLE, "Connection failed")
        )
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(ptz_service_url, camera_id, False, False),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

            mock_http_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ptz_stream_interrupt():
    """PTZストリームでの中断フラグ処理テスト"""
    camera_id = "test-camera-4"
    ptz_service_url = "http://localhost:8081"

    polling_response = ptz_service_pb2.PollingResponse()
    polling_response.timestamp_ms = 3000
    polling_response.interrupt = True

    with patch("ptz.ptz_service_connect.PTZServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.polling = AsyncMock(return_value=polling_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(ptz_service_url, camera_id, False, False),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

            mock_client.polling.assert_called()


@pytest.mark.asyncio
async def test_handle_ptz_stream_with_next_command():
    """PTZストリームでのプリフェッチ（next_command）処理テスト"""
    camera_id = "test-camera-5"
    ptz_service_url = "http://localhost:8081"

    polling_response = ptz_service_pb2.PollingResponse()
    polling_response.timestamp_ms = 4000
    polling_response.next_command.task_id = "next-task-1"
    polling_response.next_command.layer = (
        ptz_service_pb2.CommandLayer.COMMAND_LAYER_CINEMATIC
    )

    with patch("ptz.ptz_service_connect.PTZServiceClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.polling = AsyncMock(return_value=polling_response)
        mock_client_class.return_value = mock_client

        with patch("ptz.httpx.AsyncClient") as mock_http_client_class:
            mock_http_client = AsyncMock()
            mock_http_client.aclose = AsyncMock()
            mock_http_client_class.return_value = mock_http_client

            try:
                await asyncio.wait_for(
                    handle_ptz_stream(
                        ptz_service_url, camera_id, False, True, virtual_ptz=True
                    ),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

            mock_client.polling.assert_called()
