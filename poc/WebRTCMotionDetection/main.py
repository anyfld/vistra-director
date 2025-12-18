"""
go2rtcのWebRTC映像を受信してYOLOv8で物体検知・動体検知を行うプログラム

aiortcを使用してWHEP (WebRTC-HTTP Egress Protocol) でgo2rtcに接続し、
リアルタイム映像を受信してUltralytics YOLOv8で物体検知を行います。
"""

import argparse
import asyncio
import logging
import ssl
import struct
import time
from datetime import datetime
from multiprocessing import shared_memory
from pathlib import Path
from typing import Optional

import aiohttp
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from ultralytics import YOLO

# YOLOv8のクラス名（COCO dataset）
YOLO_CLASS_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush"
]

# 共有メモリの設定
SHARED_MEMORY_NAME = "webrtc_motion_frame"
# メタデータサイズ: width(4) + height(4) + channels(4) + timestamp(8) + sequence(8) + num_detections(4) = 32バイト
METADATA_SIZE = 32
# 検出データ1件のサイズ: x1(4) + y1(4) + x2(4) + y2(4) + class_id(4) + confidence(4) = 24バイト
DETECTION_SIZE = 24
# 最大検出数
MAX_DETECTIONS = 100
# 検出データの最大サイズ
MAX_DETECTION_DATA_SIZE = DETECTION_SIZE * MAX_DETECTIONS
# 最大フレームサイズ（1920x1080x3 = 約6.2MB）
MAX_FRAME_SIZE = 1920 * 1080 * 3

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FramePublisher:
    """共有メモリを使用してフレームと検出結果を外部プロセスに公開するクラス"""

    def __init__(self, name: str = SHARED_MEMORY_NAME):
        """
        Args:
            name: 共有メモリの名前
        """
        self.name = name
        self.shm: Optional[shared_memory.SharedMemory] = None
        self.sequence = 0
        self.total_size = METADATA_SIZE + MAX_DETECTION_DATA_SIZE + MAX_FRAME_SIZE

    def setup(self) -> None:
        """共有メモリを作成または接続"""
        try:
            # 既存の共有メモリを削除してから作成
            try:
                existing_shm = shared_memory.SharedMemory(name=self.name)
                existing_shm.close()
                existing_shm.unlink()
                logger.info(f"既存の共有メモリ '{self.name}' を削除しました")
            except FileNotFoundError:
                pass

            self.shm = shared_memory.SharedMemory(
                name=self.name, create=True, size=self.total_size
            )
            logger.info(
                f"共有メモリ '{self.name}' を作成しました (サイズ: {self.total_size} bytes)"
            )
        except Exception as e:
            logger.error(f"共有メモリの作成に失敗: {e}")
            raise

    def publish(
        self,
        frame: np.ndarray,
        detections: Optional[list[tuple[int, int, int, int, int, float]]] = None,
    ) -> None:
        """
        フレームと検出結果を共有メモリに書き込む

        Args:
            frame: BGRフォーマットのnumpy配列（元画像、アノテーションなし）
            detections: 検出結果のリスト [(x1, y1, x2, y2, class_id, confidence), ...]
        """
        if self.shm is None:
            return

        height, width, channels = frame.shape
        frame_size = height * width * channels

        if frame_size > MAX_FRAME_SIZE:
            logger.warning(
                f"フレームサイズ ({frame_size}) が最大サイズ ({MAX_FRAME_SIZE}) を超えています"
            )
            return

        # 検出数
        num_detections = 0
        if detections:
            num_detections = min(len(detections), MAX_DETECTIONS)

        # メタデータをパック
        timestamp = time.time()
        self.sequence += 1
        metadata = struct.pack(
            "<IIIdQI", width, height, channels, timestamp, self.sequence, num_detections
        )

        # 共有メモリに書き込み
        offset = 0

        # 1. メタデータ
        self.shm.buf[offset : offset + METADATA_SIZE] = metadata
        offset += METADATA_SIZE

        # 2. 検出データ
        if detections and num_detections > 0:
            for i in range(num_detections):
                x1, y1, x2, y2, class_id, confidence = detections[i]
                det_data = struct.pack("<IIIIIf", x1, y1, x2, y2, class_id, confidence)
                self.shm.buf[offset : offset + DETECTION_SIZE] = det_data
                offset += DETECTION_SIZE

        # 検出データ領域の残りをスキップ
        offset = METADATA_SIZE + MAX_DETECTION_DATA_SIZE

        # 3. フレームデータ
        self.shm.buf[offset : offset + frame_size] = frame.tobytes()

    def close(self) -> None:
        """共有メモリをクローズ"""
        if self.shm:
            try:
                self.shm.close()
                self.shm.unlink()
                logger.info(f"共有メモリ '{self.name}' をクローズしました")
            except Exception as e:
                logger.warning(f"共有メモリのクローズ中にエラー: {e}")
            self.shm = None


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
        kernel = np.ones((5, 5), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=2)

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
        imgsz: int = 640,
        half: bool = False,
        max_det: int = 300,
        enable_frame_sharing: bool = False,
        manual_crop_dir: str = "manual_crops",
        manual_crop_padding: int = 10,
        manual_crop_add_label: bool = False,
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
            imgsz: YOLO推論時の画像サイズ（小さいほど高速）
            half: 半精度演算を使用（GPU時に高速化）
            max_det: 最大検出数
            enable_frame_sharing: 共有メモリでフレームを外部プロセスに公開するか
            manual_crop_dir: 手動クロップの出力ディレクトリ
            manual_crop_padding: 手動クロップ時の余白ピクセル
            manual_crop_add_label: 手動クロップ画像にラベル（連番-オブジェクト名）を追加するか
        """
        self.go2rtc_url = go2rtc_url.rstrip("/")
        self.stream_name = stream_name
        self.model_name = model_name
        self.enable_object_detection = enable_object_detection
        self.enable_motion_detection = enable_motion_detection
        self.confidence_threshold = confidence_threshold
        self.insecure = insecure
        self.imgsz = imgsz
        self.half = half
        self.max_det = max_det
        self.enable_frame_sharing = enable_frame_sharing
        self.manual_crop_dir = Path(manual_crop_dir)
        self.manual_crop_padding = manual_crop_padding
        self.manual_crop_add_label = manual_crop_add_label

        self.pc: Optional[RTCPeerConnection] = None
        self.model: Optional[YOLO] = None
        self.motion_detector: Optional[MotionDetector] = None
        self.frame_publisher: Optional[FramePublisher] = None

        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self.last_fps_time = time.time()

        # 最新フレームを保持（ダブルバッファリング）
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_lock = asyncio.Lock()

        # 手動クロップ用：最新の元画像と検出結果を保持
        self.latest_raw_frame: Optional[np.ndarray] = None
        self.latest_detections: list[tuple[int, int, int, int, int, float]] = []
        self.manual_crop_count = 0

        # 処理待ちフレーム（最新のみ保持して古いフレームはスキップ）
        self._pending_frame: Optional[np.ndarray] = None
        self._pending_frame_lock = asyncio.Lock()

        # 推論時間の計測
        self.inference_time_ms = 0.0

    async def setup(self) -> None:
        """モデルとコンポーネントの初期化"""
        if self.enable_object_detection:
            logger.info(f"YOLOv8モデルをロード中: {self.model_name}")
            self.model = YOLO(self.model_name)

            # モデルのウォームアップ（初回推論を高速化）
            logger.info(
                f"モデルをウォームアップ中 (imgsz={self.imgsz}, half={self.half})..."
            )
            dummy_img = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            self.model(
                dummy_img,
                verbose=False,
                imgsz=self.imgsz,
                half=self.half,
                max_det=self.max_det,
            )
            logger.info("モデルのロード・ウォームアップ完了")
        else:
            logger.info("物体検知（YOLO）は無効です")

        if self.enable_motion_detection:
            self.motion_detector = MotionDetector()
            logger.info("動体検知を有効化")
        else:
            logger.info("動体検知は無効です")

        if self.enable_frame_sharing:
            self.frame_publisher = FramePublisher()
            self.frame_publisher.setup()
            logger.info("フレーム共有（共有メモリ）を有効化")
        else:
            logger.info("フレーム共有は無効です")

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

    async def _process_video_track(self, track) -> None:
        """ビデオトラックからフレームを処理"""
        logger.info("ビデオトラック処理を開始")
        self.running = True

        # フレーム受信と処理を分離して並列化
        asyncio.create_task(self._frame_processor())

        while self.running:
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=5.0)
                # フレームをNumPy配列に変換して保持（最新のみ）
                img = frame.to_ndarray(format="bgr24")
                async with self._pending_frame_lock:
                    self._pending_frame = img
            except asyncio.TimeoutError:
                logger.warning("フレーム受信タイムアウト")
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"フレーム処理エラー: {e}")
                break

        logger.info("ビデオトラック処理を終了")

    async def _frame_processor(self) -> None:
        """フレームを処理するワーカー（別タスクで実行）"""
        while self.running:
            # 処理待ちフレームを取得
            async with self._pending_frame_lock:
                img = self._pending_frame
                self._pending_frame = None

            if img is None:
                # フレームがない場合は少し待機
                await asyncio.sleep(0.001)
                continue

            await self._handle_frame(img)

    async def _handle_frame(self, img: np.ndarray) -> None:
        """フレームを処理して物体検知を実行"""
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
        detections: list[tuple[int, int, int, int, int, float]] = []
        if self.enable_object_detection and self.model:
            inference_start = time.perf_counter()
            results = self.model(
                img,
                verbose=False,
                conf=self.confidence_threshold,
                imgsz=self.imgsz,
                half=self.half,
                max_det=self.max_det,
            )
            self.inference_time_ms = (time.perf_counter() - inference_start) * 1000
            annotated_frame = results[0].plot()
            detection_count = len(results[0].boxes)

            # 検出結果を抽出（共有メモリ用）
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                class_id = int(box.cls[0].cpu().numpy())
                confidence = float(box.conf[0].cpu().numpy())
                detections.append((x1, y1, x2, y2, class_id, confidence))
        else:
            # 物体検知が無効な場合は直接使用（コピーしない）
            annotated_frame = img

        # 動体検知結果を描画（動体検知が有効な場合のみコピーが必要）
        if self.enable_motion_detection:
            if not self.enable_object_detection:
                annotated_frame = img.copy()
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
            status_text += f" | Inf: {self.inference_time_ms:.0f}ms"
            status_text += f" | Det: {detection_count}"
        if self.enable_motion_detection:
            motion_status = "Y" if motion_detected else "N"
            status_text += f" | Mot: {motion_status}"

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
            # 手動クロップ用に元画像と検出結果を保持
            self.latest_raw_frame = img.copy()
            self.latest_detections = detections.copy() if detections else []

        # 共有メモリにフレームと検出結果を公開（元画像を使用）
        if self.frame_publisher:
            self.frame_publisher.publish(img, detections if detections else None)

    def _manual_crop_objects(self) -> int:
        """現在の検出オブジェクトを手動でクロップして保存"""
        if self.latest_raw_frame is None or not self.latest_detections:
            logger.warning("クロップするオブジェクトがありません")
            return 0

        # 出力ディレクトリを作成
        self.manual_crop_dir.mkdir(parents=True, exist_ok=True)

        frame = self.latest_raw_frame
        height, width = frame.shape[:2]
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        saved_count = 0

        for i, (x1, y1, x2, y2, class_id, confidence) in enumerate(self.latest_detections):
            # クラス名を取得
            class_name_raw = YOLO_CLASS_NAMES[class_id] if 0 <= class_id < len(YOLO_CLASS_NAMES) else f"class_{class_id}"
            class_name = class_name_raw.replace(" ", "_")

            # パディングを追加してクロップ
            crop_x1 = max(0, x1 - self.manual_crop_padding)
            crop_y1 = max(0, y1 - self.manual_crop_padding)
            crop_x2 = min(width, x2 + self.manual_crop_padding)
            crop_y2 = min(height, y2 + self.manual_crop_padding)

            cropped = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()

            # ラベルを追加（オプション）
            if self.manual_crop_add_label:
                label_text = f"{i + 1}-{class_name_raw}"
                crop_h, crop_w = cropped.shape[:2]

                # フォントサイズを画像サイズに応じて調整
                font_scale = max(0.4, min(crop_w, crop_h) / 200)
                thickness = max(1, int(font_scale * 2))

                # テキストサイズを取得
                (text_w, text_h), baseline = cv2.getTextSize(
                    label_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
                )

                # 背景を描画（左上）
                padding = 4
                cv2.rectangle(
                    cropped,
                    (0, 0),
                    (text_w + padding * 2, text_h + baseline + padding * 2),
                    (0, 0, 0),
                    -1,
                )

                # テキストを描画
                cv2.putText(
                    cropped,
                    label_text,
                    (padding, text_h + padding),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (255, 255, 255),
                    thickness,
                )

            # ファイル名を生成
            self.manual_crop_count += 1
            filename = f"manual_{class_name}_{dt.strftime('%Y%m%d_%H%M%S')}_{self.manual_crop_count:04d}.jpg"
            filepath = self.manual_crop_dir / filename

            # 保存
            cv2.imwrite(str(filepath), cropped, [cv2.IMWRITE_JPEG_QUALITY, 90])
            saved_count += 1
            logger.info(
                f"[手動クロップ] {i + 1}-{class_name_raw}: {filepath.name} "
                f"(サイズ: {crop_x2 - crop_x1}x{crop_y2 - crop_y1}, conf: {confidence:.2f})"
            )

        return saved_count

    async def display_loop(self) -> None:
        """OpenCVウィンドウでフレームを表示"""
        window_name = f"WebRTC Object Detection - {self.stream_name}"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        logger.info("映像表示を開始します。'q'キーで終了、SPACEキーで手動クロップ。")

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
            elif key == ord(" "):  # スペースキー
                logger.info("スペースキーが押されました - 手動クロップを実行")
                count = self._manual_crop_objects()
                if count > 0:
                    logger.info(f"手動クロップ完了: {count}個のオブジェクトを保存しました")

            # 表示ループの待機時間を最小化
            await asyncio.sleep(0.001)

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
        if self.frame_publisher:
            self.frame_publisher.close()
            self.frame_publisher = None
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
        "--imgsz",
        type=int,
        default=640,
        help="YOLO推論画像サイズ（小さいほど高速、デフォルト: 640、低遅延なら320推奨）",
    )
    parser.add_argument(
        "--half",
        action="store_true",
        help="半精度演算を使用（GPU時に高速化）",
    )
    parser.add_argument(
        "--max-det",
        type=int,
        default=300,
        help="最大検出数（デフォルト: 300）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細なログを出力する",
    )
    parser.add_argument(
        "--share-frame",
        action="store_true",
        help="共有メモリでフレームを外部プロセスに公開する（ObjectCrop連携用）",
    )
    parser.add_argument(
        "--manual-crop-dir",
        type=str,
        default="manual_crops",
        help="手動クロップの出力ディレクトリ（デフォルト: manual_crops）",
    )
    parser.add_argument(
        "--manual-crop-padding",
        type=int,
        default=10,
        help="手動クロップ時の余白ピクセル（デフォルト: 10）",
    )
    parser.add_argument(
        "--manual-crop-label",
        action="store_true",
        help="手動クロップ画像にラベル（連番-オブジェクト名）を追加する",
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
        imgsz=args.imgsz,
        half=args.half,
        max_det=args.max_det,
        enable_frame_sharing=args.share_frame,
        manual_crop_dir=args.manual_crop_dir,
        manual_crop_padding=args.manual_crop_padding,
        manual_crop_add_label=args.manual_crop_label,
    )

    try:
        asyncio.run(detector.run())
    except KeyboardInterrupt:
        logger.info("プログラムが中断されました")


if __name__ == "__main__":
    main()
