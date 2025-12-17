"""
go2rtcのWebRTC映像を受信してYOLOv8で物体検知・動体検知を行うプログラム

aiortcを使用してWHEP (WebRTC-HTTP Egress Protocol) でgo2rtcに接続し、
リアルタイム映像を受信してUltralytics YOLOv8で物体検知を行います。
"""

import argparse
import asyncio
import logging
import ssl
import time
from typing import Optional

import aiohttp
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame
from ultralytics import YOLO

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MotionDetector:
    """動体検知を行うクラス"""

    def __init__(self, threshold: float = 25.0, min_area: int = 500):
        """
        Args:
            threshold: フレーム差分の閾値
            min_area: 検出する最小面積
        """
        self.threshold = threshold
        self.min_area = min_area
        self.prev_frame: Optional[np.ndarray] = None

    def detect(self, frame: np.ndarray) -> tuple[bool, list[tuple[int, int, int, int]]]:
        """
        動体検知を実行

        Args:
            frame: 入力フレーム (BGR形式)

        Returns:
            (動体検知フラグ, 動体領域のリスト[(x, y, w, h), ...])
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self.prev_frame is None:
            self.prev_frame = gray
            return False, []

        # フレーム差分を計算
        frame_delta = cv2.absdiff(self.prev_frame, gray)
        thresh = cv2.threshold(frame_delta, self.threshold, 255, cv2.THRESH_BINARY)[1]

        # 膨張処理で穴を埋める
        thresh = cv2.dilate(thresh, None, iterations=2)

        # 輪郭を検出
        contours, _ = cv2.findContours(
            thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        motion_regions: list[tuple[int, int, int, int]] = []
        for contour in contours:
            if cv2.contourArea(contour) < self.min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            motion_regions.append((x, y, w, h))

        self.prev_frame = gray
        return len(motion_regions) > 0, motion_regions


class WebRTCObjectDetector:
    """WebRTC映像を受信して物体検知を行うクラス"""

    def __init__(
        self,
        go2rtc_url: str,
        stream_name: str,
        model_name: str = "yolov8n.pt",
        enable_object_detection: bool = True,
        enable_motion_detection: bool = True,
        confidence_threshold: float = 0.5,
        insecure: bool = False,
    ):
        """
        Args:
            go2rtc_url: go2rtcサーバーのベースURL (例: https://172.20.10.3)
            stream_name: ストリーム名
            model_name: YOLOv8モデル名
            enable_object_detection: 物体検知（YOLO）を有効にするか
            enable_motion_detection: 動体検知を有効にするか
            confidence_threshold: 物体検知の信頼度閾値
            insecure: SSL証明書の検証をスキップするか
        """
        self.go2rtc_url = go2rtc_url.rstrip("/")
        self.stream_name = stream_name
        self.model_name = model_name
        self.enable_object_detection = enable_object_detection
        self.enable_motion_detection = enable_motion_detection
        self.confidence_threshold = confidence_threshold
        self.insecure = insecure

        self.pc: Optional[RTCPeerConnection] = None
        self.model: Optional[YOLO] = None
        self.motion_detector: Optional[MotionDetector] = None

        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self.last_fps_time = time.time()

        # 最新フレームを保持
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_lock = asyncio.Lock()

    async def setup(self) -> None:
        """モデルとコンポーネントの初期化"""
        if self.enable_object_detection:
            logger.info(f"YOLOv8モデルをロード中: {self.model_name}")
            self.model = YOLO(self.model_name)
            logger.info("モデルのロード完了")
        else:
            logger.info("物体検知（YOLO）は無効です")

        if self.enable_motion_detection:
            self.motion_detector = MotionDetector()
            logger.info("動体検知を有効化")
        else:
            logger.info("動体検知は無効です")

    async def connect_whep(self) -> None:
        """WHEPを使用してgo2rtcに接続"""
        whep_url = f"{self.go2rtc_url}/api/webrtc?src={self.stream_name}"

        self.pc = RTCPeerConnection()

        # 接続完了を待つためのイベント
        self._connected_event = asyncio.Event()
        self._track_event = asyncio.Event()

        # ビデオトラックのみを受信
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        async def on_track(track):
            logger.info(f"トラック受信: {track.kind}")
            if track.kind == "video":
                self._track_event.set()
                asyncio.create_task(self._process_video_track(track))

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"接続状態: {self.pc.connectionState}")
            if self.pc.connectionState == "connected":
                self._connected_event.set()
            elif self.pc.connectionState in ("failed", "closed"):
                self._connected_event.set()  # エラー時もイベントを発火

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
        ssl_context: Optional[ssl.SSLContext] = None
        if self.insecure:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.warning("SSL証明書の検証を無効化しています")

        connector = aiohttp.TCPConnector(ssl=ssl_context) if self.insecure else None

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

    async def _process_video_track(self, track) -> None:
        """ビデオトラックからフレームを処理"""
        logger.info("ビデオトラック処理を開始")
        self.running = True

        while self.running:
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=5.0)
                await self._handle_frame(frame)
            except asyncio.TimeoutError:
                logger.warning("フレーム受信タイムアウト")
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"フレーム処理エラー: {e}")
                break

        logger.info("ビデオトラック処理を終了")

    async def _handle_frame(self, frame: VideoFrame) -> None:
        """フレームを処理して物体検知を実行"""
        # フレームをNumPy配列に変換 (RGB -> BGR)
        img = frame.to_ndarray(format="bgr24")

        # FPS計算
        self.frame_count += 1
        current_time = time.time()
        if current_time - self.last_fps_time >= 1.0:
            self.fps = self.frame_count / (current_time - self.last_fps_time)
            self.frame_count = 0
            self.last_fps_time = current_time

        # 動体検知（有効な場合）
        motion_detected = False
        motion_regions: list[tuple[int, int, int, int]] = []
        if self.motion_detector:
            motion_detected, motion_regions = self.motion_detector.detect(img)

        # YOLOv8で物体検知（有効な場合）
        detection_count = 0
        if self.enable_object_detection and self.model:
            results = self.model(img, verbose=False, conf=self.confidence_threshold)
            annotated_frame = results[0].plot()
            detection_count = len(results[0].boxes)
        else:
            annotated_frame = img.copy()

        # 動体検知結果を描画
        if self.enable_motion_detection:
            for x, y, w, h in motion_regions:
                cv2.rectangle(annotated_frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(
                    annotated_frame,
                    "Motion",
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),
                    2,
                )

        # ステータス情報を表示
        status_text = f"FPS: {self.fps:.1f}"
        if self.enable_object_detection:
            status_text += f" | Detections: {detection_count}"
        if self.enable_motion_detection:
            motion_status = "Yes" if motion_detected else "No"
            status_text += f" | Motion: {motion_status}"

        cv2.putText(
            annotated_frame,
            status_text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        # 検知結果をコンソールに出力（動きがある場合のみ）
        if motion_detected or detection_count > 0:
            logger.debug(
                f"検知: 物体={detection_count}, 動体={'あり' if motion_detected else 'なし'}"
            )

        # 最新フレームを更新
        async with self.frame_lock:
            self.latest_frame = annotated_frame

    async def display_loop(self) -> None:
        """OpenCVウィンドウでフレームを表示"""
        window_name = f"WebRTC Object Detection - {self.stream_name}"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        logger.info("映像表示を開始します。'q'キーで終了します。")

        # runningがTrueになるまで待機
        wait_count = 0
        while not self.running and wait_count < 100:
            await asyncio.sleep(0.1)
            wait_count += 1

        if not self.running:
            logger.error("ビデオ処理が開始されませんでした")
            return

        while self.running:
            async with self.frame_lock:
                frame = self.latest_frame

            if frame is not None:
                cv2.imshow(window_name, frame)
            else:
                # フレームがまだない場合はプレースホルダーを表示
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    placeholder,
                    "Waiting for video...",
                    (150, 240),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255),
                    2,
                )
                cv2.imshow(window_name, placeholder)

            # キー入力チェック（1msの遅延）
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                logger.info("終了キーが押されました")
                self.running = False
                break

            await asyncio.sleep(0.01)

        cv2.destroyAllWindows()

    async def run(self) -> None:
        """メイン実行ループ"""
        try:
            await self.setup()
            await self.connect_whep()
            await self.display_loop()
        except Exception as e:
            logger.error(f"エラーが発生しました: {e}")
            raise
        finally:
            await self.close()

    async def close(self) -> None:
        """リソースをクリーンアップ"""
        self.running = False
        if self.pc:
            await self.pc.close()
            self.pc = None
        cv2.destroyAllWindows()
        logger.info("接続を閉じました")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="go2rtcのWebRTC映像を受信してYOLOv8で物体検知を行うプログラム"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="https://172.20.10.3",
        help="go2rtcサーバーのベースURL（デフォルト: https://172.20.10.3）",
    )
    parser.add_argument(
        "--stream",
        type=str,
        default="camera",
        help="go2rtcのストリーム名（デフォルト: camera）",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="SSL証明書の検証をスキップする（自己署名証明書用）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="YOLOv8モデル（yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt）",
    )
    parser.add_argument(
        "--no-detection",
        action="store_true",
        help="物体検知（YOLO）を無効にする",
    )
    parser.add_argument(
        "--no-motion",
        action="store_true",
        help="動体検知を無効にする",
    )
    parser.add_argument(
        "--video-only",
        action="store_true",
        help="映像のみ表示（物体検知・動体検知を両方無効）",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="物体検知の信頼度閾値（0.0-1.0、デフォルト: 0.5）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細なログを出力する",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --video-only は物体検知と動体検知を両方無効にする
    enable_object = not (args.no_detection or args.video_only)
    enable_motion = not (args.no_motion or args.video_only)

    detector = WebRTCObjectDetector(
        go2rtc_url=args.url,
        stream_name=args.stream,
        model_name=args.model,
        enable_object_detection=enable_object,
        enable_motion_detection=enable_motion,
        confidence_threshold=args.confidence,
        insecure=args.insecure,
    )

    try:
        asyncio.run(detector.run())
    except KeyboardInterrupt:
        logger.info("プログラムが中断されました")


if __name__ == "__main__":
    main()
