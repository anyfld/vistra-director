#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebRTC受信処理"""

import asyncio
import logging
import ssl
from typing import Optional

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription

logger = logging.getLogger(__name__)


class WebRTCReceiver:
    """WebRTCストリームを受信するクラス"""

    def __init__(
        self,
        webrtc_url: str,
        stream_key: str,
        insecure: bool = False,
    ) -> None:
        """
        Args:
            webrtc_url: WebRTCベースURL（テンプレートを含む可能性あり）
            stream_key: ストリームキー（webrtc_connection_name）
            insecure: SSL証明書の検証をスキップするか
        """
        self.webrtc_url = webrtc_url
        self.stream_key = stream_key
        self.insecure = insecure
        self.pc: Optional[RTCPeerConnection] = None
        self._connected_event = asyncio.Event()
        self._track_event = asyncio.Event()
        self.running = False

    async def connect(self) -> None:
        """WebRTC接続を確立"""
        # URLテンプレートを処理（{key}をstream_keyで置換）
        url = self.webrtc_url.replace("{key}", self.stream_key)
        # テンプレートがない場合は、クエリパラメータとして追加
        if "{key}" not in self.webrtc_url and "src=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}src={self.stream_key}"

        whep_url = url
        if not whep_url.endswith("/api/webrtc"):
            if not whep_url.endswith("/"):
                whep_url += "/"
            whep_url += "api/webrtc"
        if "src=" not in whep_url:
            separator = "&" if "?" in whep_url else "?"
            whep_url = f"{whep_url}{separator}src={self.stream_key}"

        logger.info(f"WebRTC接続を開始: {whep_url}")

        self.pc = RTCPeerConnection()

        # 接続完了を待つためのイベント
        self._connected_event = asyncio.Event()
        self._track_event = asyncio.Event()

        # ビデオトラックのみを受信
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        async def on_track(track) -> None:  # type: ignore[no-untyped-def]
            logger.info(f"トラック受信: {track.kind}")
            if track.kind == "video":
                self._track_event.set()
                asyncio.create_task(self._process_video_track(track))

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            if self.pc is None:
                return
            logger.info(f"接続状態: {self.pc.connectionState}")
            if self.pc.connectionState == "connected":
                self._connected_event.set()
            elif self.pc.connectionState in ("failed", "closed"):
                self._connected_event.set()

        # SDPオファーを作成
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # ICE候補の収集を待つ
        logger.info("ICE候補を収集中...")
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)
        logger.info("ICE候補の収集完了")

        logger.info(f"WHEPエンドポイントに接続中: {whep_url}")

        # SSL設定（自己署名証明書対応）
        connector: Optional[aiohttp.TCPConnector] = None
        if self.insecure:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.warning("SSL証明書の検証を無効化しています")
            connector = aiohttp.TCPConnector(ssl=ssl_context)

        # WHEPエンドポイントにオファーを送信
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                whep_url,
                data=self.pc.localDescription.sdp,
                headers={"Content-Type": "application/sdp"},
            ) as response:
                if response.status != 201:
                    error_text = await response.text()
                    raise RuntimeError(
                        f"WHEPエンドポイントへの接続に失敗: {response.status} - {error_text}"
                    )

                answer_sdp = await response.text()

        # SDPアンサーを設定
        answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
        await self.pc.setRemoteDescription(answer)

        logger.info("SDP交換完了、接続確立を待機中...")

        # 接続確立を待つ（タイムアウト10秒）
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("接続確立タイムアウト、トラック受信を待機...")

        # トラック受信を待つ（タイムアウト10秒）
        try:
            await asyncio.wait_for(self._track_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise RuntimeError("ビデオトラックの受信がタイムアウトしました")

        logger.info("WebRTC接続確立完了")
        self.running = True

    async def _process_video_track(self, track) -> None:
        """ビデオトラックからフレームを処理"""
        logger.info(f"ビデオトラック処理を開始: {self.stream_key}")
        while self.running:
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=5.0)
                # フレームを受信（現在はログ出力のみ、必要に応じて処理を追加）
                logger.debug(f"フレーム受信: {self.stream_key}")
            except asyncio.TimeoutError:
                logger.warning(f"フレーム受信タイムアウト: {self.stream_key}")
                break
            except Exception as e:
                logger.error(f"フレーム処理エラー: {e}", exc_info=True)
                break

    async def disconnect(self) -> None:
        """WebRTC接続を切断"""
        logger.info(f"WebRTC接続を切断: {self.stream_key}")
        self.running = False
        if self.pc:
            await self.pc.close()
            self.pc = None
