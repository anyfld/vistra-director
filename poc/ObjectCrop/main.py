"""
WebRTCMotionDetectionの映像をクロップしてAI用画像を生成するプログラム

共有メモリを介してWebRTCMotionDetectionから映像フレームを受信し、
定期的にクロップしてAI解析用の画像として保存します。
"""

import argparse
import asyncio
import logging
import struct
from datetime import datetime
from multiprocessing import shared_memory
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 共有メモリの設定（WebRTCMotionDetectionと同じ値）
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

# YOLOv8のクラス名（COCO dataset）
YOLO_CLASS_NAMES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]


class Detection:
    """検出結果を表すクラス"""

    def __init__(
        self, x1: int, y1: int, x2: int, y2: int, class_id: int, confidence: float
    ):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.class_id = class_id
        self.confidence = confidence

    @property
    def class_name(self) -> str:
        """クラス名を取得"""
        if 0 <= self.class_id < len(YOLO_CLASS_NAMES):
            return YOLO_CLASS_NAMES[self.class_id]
        return f"class_{self.class_id}"

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        """中心座標を取得"""
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> int:
        """面積を取得"""
        return self.width * self.height

    def iou(self, other: "Detection") -> float:
        """IoU（Intersection over Union）を計算"""
        # 交差領域を計算
        x1 = max(self.x1, other.x1)
        y1 = max(self.y1, other.y1)
        x2 = min(self.x2, other.x2)
        y2 = min(self.y2, other.y2)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        union = self.area + other.area - intersection

        return intersection / union if union > 0 else 0.0

    def __repr__(self) -> str:
        return f"Detection({self.class_name}, conf={self.confidence:.2f}, bbox=[{self.x1},{self.y1},{self.x2},{self.y2}])"


class TrackedObject:
    """追跡中のオブジェクト"""

    def __init__(self, detection: Detection, timestamp: float, track_id: int):
        self.detection = detection
        self.last_seen = timestamp
        self.first_seen = timestamp
        self.track_id = track_id
        self.cropped = False  # クロップ済みフラグ

    def update(self, detection: Detection, timestamp: float) -> None:
        """検出情報を更新"""
        self.detection = detection
        self.last_seen = timestamp


class ObjectTracker:
    """シンプルなオブジェクト追跡クラス（IoUベース）"""

    def __init__(self, iou_threshold: float = 0.3, timeout: float = 2.0):
        """
        Args:
            iou_threshold: 同一オブジェクトと判定するIoU閾値
            timeout: オブジェクトが消えたと判定する時間（秒）
        """
        self.iou_threshold = iou_threshold
        self.timeout = timeout
        self.tracked_objects: dict[int, TrackedObject] = {}  # track_id -> TrackedObject
        self.next_track_id = 0

    def update(
        self, detections: list[Detection], timestamp: float
    ) -> list[tuple[Detection, TrackedObject, bool]]:
        """
        検出結果で追跡を更新

        Args:
            detections: 検出結果リスト
            timestamp: 現在のタイムスタンプ

        Returns:
            [(detection, tracked_object, is_new), ...] のリスト
        """
        results: list[tuple[Detection, TrackedObject, bool]] = []

        # タイムアウトしたオブジェクトを削除
        expired_ids = [
            track_id
            for track_id, obj in self.tracked_objects.items()
            if timestamp - obj.last_seen > self.timeout
        ]
        for track_id in expired_ids:
            logger.debug(f"オブジェクト #{track_id} がタイムアウト（消失）")
            del self.tracked_objects[track_id]

        # 各検出をマッチング
        used_track_ids: set[int] = set()

        for detection in detections:
            best_match: Optional[TrackedObject] = None
            best_iou = 0.0

            # 同じクラスの既存オブジェクトとマッチング
            for track_id, tracked in self.tracked_objects.items():
                if track_id in used_track_ids:
                    continue
                if tracked.detection.class_id != detection.class_id:
                    continue

                iou = detection.iou(tracked.detection)
                if iou > self.iou_threshold and iou > best_iou:
                    best_iou = iou
                    best_match = tracked

            if best_match is not None:
                # 既存オブジェクトを更新
                best_match.update(detection, timestamp)
                used_track_ids.add(best_match.track_id)
                results.append((detection, best_match, False))  # is_new=False
            else:
                # 新しいオブジェクト
                track_id = self.next_track_id
                self.next_track_id += 1
                tracked = TrackedObject(detection, timestamp, track_id)
                self.tracked_objects[track_id] = tracked
                used_track_ids.add(track_id)
                results.append((detection, tracked, True))  # is_new=True
                logger.debug(f"新しいオブジェクト #{track_id}: {detection.class_name}")

        return results

    def reset(self) -> None:
        """追跡をリセット"""
        self.tracked_objects.clear()
        self.next_track_id = 0


class FrameSubscriber:
    """共有メモリからフレームと検出結果を読み取るクラス"""

    def __init__(self, name: str = SHARED_MEMORY_NAME, retry_interval: float = 1.0):
        """
        Args:
            name: 共有メモリの名前
            retry_interval: 共有メモリ接続リトライ間隔（秒）
        """
        self.name = name
        self.retry_interval = retry_interval
        self.shm: Optional[shared_memory.SharedMemory] = None
        self.last_sequence = 0

    async def connect(self) -> bool:
        """共有メモリに接続"""
        while True:
            try:
                self.shm = shared_memory.SharedMemory(name=self.name)
                logger.info(f"共有メモリ '{self.name}' に接続しました")
                return True
            except FileNotFoundError:
                logger.info(
                    f"共有メモリ '{self.name}' が見つかりません。"
                    f"{self.retry_interval}秒後にリトライします..."
                )
                logger.info(
                    "WebRTCMotionDetectionを --share-frame オプション付きで起動してください"
                )
                await asyncio.sleep(self.retry_interval)
            except Exception as e:
                logger.error(f"共有メモリへの接続に失敗: {e}")
                await asyncio.sleep(self.retry_interval)

    def read_frame(self) -> Optional[tuple[np.ndarray, list[Detection], float, int]]:
        """
        共有メモリからフレームと検出結果を読み取る

        Returns:
            (フレーム, 検出結果リスト, タイムスタンプ, シーケンス番号) または None
        """
        if self.shm is None:
            return None

        try:
            assert self.shm.buf is not None  # 型チェッカー用
            # メタデータを読み取り
            metadata = bytes(self.shm.buf[:METADATA_SIZE])
            width, height, channels, timestamp, sequence, num_detections = (
                struct.unpack("<IIIdQI", metadata)
            )

            # 新しいフレームがない場合はスキップ
            if sequence == self.last_sequence:
                return None

            self.last_sequence = sequence

            # フレームサイズを計算
            frame_size = width * height * channels

            if frame_size == 0 or frame_size > MAX_FRAME_SIZE:
                return None

            # 検出データを読み取り
            detections: list[Detection] = []
            offset = METADATA_SIZE
            for _ in range(min(num_detections, MAX_DETECTIONS)):
                det_data = bytes(self.shm.buf[offset : offset + DETECTION_SIZE])
                x1, y1, x2, y2, class_id, confidence = struct.unpack(
                    "<IIIIIf", det_data
                )
                detections.append(Detection(x1, y1, x2, y2, class_id, confidence))
                offset += DETECTION_SIZE

            # フレームデータを読み取り
            frame_offset = METADATA_SIZE + MAX_DETECTION_DATA_SIZE
            frame_data = bytes(self.shm.buf[frame_offset : frame_offset + frame_size])
            frame = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                (height, width, channels)
            )

            return frame.copy(), detections, timestamp, sequence

        except Exception as e:
            logger.error(f"フレーム読み取りエラー: {e}")
            return None

    def close(self) -> None:
        """共有メモリをクローズ（unlinkしない）"""
        if self.shm:
            try:
                self.shm.close()
                logger.info(f"共有メモリ '{self.name}' から切断しました")
            except Exception as e:
                logger.warning(f"共有メモリの切断中にエラー: {e}")
            self.shm = None


class ImageCropper:
    """検出されたオブジェクトをクロップして保存するクラス"""

    def __init__(
        self,
        output_dir: str = "cropped_images",
        quality: int = 90,
        format: str = "jpeg",
        padding: int = 10,
        min_size: int = 32,
        target_classes: Optional[list[str]] = None,
    ):
        """
        Args:
            output_dir: 出力ディレクトリ
            quality: JPEG品質 (1-100)
            format: 出力フォーマット ("jpeg", "png")
            padding: クロップ時の余白ピクセル
            min_size: 最小クロップサイズ（これより小さいものは無視）
            target_classes: クロップ対象のクラス名リスト（Noneの場合は全クラス）
        """
        self.output_dir = Path(output_dir)
        self.quality = quality
        self.format = format.lower()
        self.padding = padding
        self.min_size = min_size
        self.target_classes = target_classes

        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"出力ディレクトリ: {self.output_dir.absolute()}")
        if target_classes:
            logger.info(f"対象クラス: {', '.join(target_classes)}")

    def crop_detection(
        self, frame: np.ndarray, detection: Detection
    ) -> Optional[np.ndarray]:
        """
        検出結果に基づいてフレームをクロップする

        Args:
            frame: 入力フレーム (BGR形式)
            detection: 検出結果

        Returns:
            クロップされたフレーム、または None（対象外の場合）
        """
        # 対象クラスのフィルタリング
        if self.target_classes and detection.class_name not in self.target_classes:
            return None

        # サイズチェック
        if detection.width < self.min_size or detection.height < self.min_size:
            return None

        height, width = frame.shape[:2]

        # パディングを追加してクロップ
        x1 = max(0, detection.x1 - self.padding)
        y1 = max(0, detection.y1 - self.padding)
        x2 = min(width, detection.x2 + self.padding)
        y2 = min(height, detection.y2 + self.padding)

        return frame[y1:y2, x1:x2]

    def save(
        self,
        frame: np.ndarray,
        detection: Detection,
        timestamp: float,
        sequence: int,
        detection_index: int,
    ) -> Optional[Path]:
        """
        クロップした画像を保存する

        Args:
            frame: クロップ済みフレーム (BGR形式)
            detection: 検出情報
            timestamp: タイムスタンプ
            sequence: シーケンス番号
            detection_index: 検出インデックス

        Returns:
            保存したファイルパス
        """
        # ファイル名を生成: {class_name}_{timestamp}_{sequence}_{index}.jpg
        dt = datetime.fromtimestamp(timestamp)
        class_name = detection.class_name.replace(" ", "_")
        filename = f"{class_name}_{dt.strftime('%Y%m%d_%H%M%S')}_{sequence:06d}_{detection_index:02d}"

        if self.format == "png":
            filepath = self.output_dir / f"{filename}.png"
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb_frame)
            img.save(filepath, "PNG")
        else:
            filepath = self.output_dir / f"{filename}.jpg"
            cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])

        return filepath

    def get_latest_images_by_class(self) -> dict[str, Path]:
        """クラスごとの最新画像パスを取得"""
        pattern = "*.jpg" if self.format == "jpeg" else "*.png"
        images = sorted(self.output_dir.glob(pattern))

        latest: dict[str, Path] = {}
        for img_path in images:
            # ファイル名からクラス名を抽出
            class_name = img_path.stem.split("_")[0]
            latest[class_name] = img_path

        return latest


class ObjectCropper:
    """新しいオブジェクトが検出された時にクロップするメインクラス"""

    def __init__(
        self,
        output_dir: str = "cropped_images",
        quality: int = 90,
        format: str = "jpeg",
        padding: int = 10,
        min_size: int = 32,
        target_classes: Optional[list[str]] = None,
        keep_latest_only: bool = False,
        max_images: int = 100,
        iou_threshold: float = 0.3,
        object_timeout: float = 2.0,
    ):
        """
        Args:
            output_dir: 出力ディレクトリ
            quality: JPEG品質
            format: 出力フォーマット
            padding: クロップ時の余白ピクセル
            min_size: 最小クロップサイズ
            target_classes: クロップ対象のクラス名リスト
            keep_latest_only: クラスごとに最新画像のみ保持するか
            max_images: 保持する最大画像数
            iou_threshold: 同一オブジェクトと判定するIoU閾値
            object_timeout: オブジェクトが消えたと判定する時間（秒）
        """
        self.keep_latest_only = keep_latest_only
        self.max_images = max_images

        self.subscriber = FrameSubscriber()
        self.cropper = ImageCropper(
            output_dir=output_dir,
            quality=quality,
            format=format,
            padding=padding,
            min_size=min_size,
            target_classes=target_classes,
        )
        self.tracker = ObjectTracker(
            iou_threshold=iou_threshold,
            timeout=object_timeout,
        )

        self.running = False
        self.crop_count = 0

    async def run(self) -> None:
        """メイン実行ループ"""
        logger.info("ObjectCropperを開始します...")
        logger.info("モード: 新しいオブジェクト検出時にクロップ")
        logger.info(
            f"IoU閾値: {self.tracker.iou_threshold}, タイムアウト: {self.tracker.timeout}秒"
        )

        # 共有メモリに接続
        await self.subscriber.connect()

        self.running = True
        logger.info("クロップを開始します。Ctrl+Cで終了します。")

        try:
            while self.running:
                # フレームと検出結果を読み取り
                result = self.subscriber.read_frame()
                if result is None:
                    await asyncio.sleep(0.01)
                    continue

                frame, detections, timestamp, sequence = result

                # オブジェクト追跡を更新
                tracked_results = self.tracker.update(detections, timestamp)

                # 新しいオブジェクトのみクロップ
                saved_paths: list[Path] = []
                for detection, tracked, is_new in tracked_results:
                    if not is_new:
                        continue  # 既存のオブジェクトはスキップ

                    cropped = self.cropper.crop_detection(frame, detection)
                    if cropped is None:
                        continue

                    filepath = self.cropper.save(
                        cropped, detection, timestamp, sequence, tracked.track_id
                    )
                    if filepath:
                        saved_paths.append(filepath)
                        self.crop_count += 1
                        logger.info(
                            f"[{self.crop_count}] 新規検出 #{tracked.track_id} {detection.class_name}: "
                            f"{filepath.name} (サイズ: {cropped.shape[1]}x{cropped.shape[0]}, "
                            f"conf: {detection.confidence:.2f})"
                        )

                if saved_paths:
                    # 古い画像を削除
                    if self.keep_latest_only:
                        self._cleanup_except_latest_per_class(saved_paths)
                    elif self.max_images > 0:
                        self._cleanup_old_images()

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info("クロップがキャンセルされました")
        finally:
            await self.close()

    def _cleanup_except_latest_per_class(self, latest_paths: list[Path]) -> None:
        """クラスごとに最新以外の画像を削除"""
        pattern = "*.jpg" if self.cropper.format == "jpeg" else "*.png"

        # 最新パスのクラス名を取得
        latest_classes = {p.stem.split("_")[0]: p for p in latest_paths}

        for img_path in self.cropper.output_dir.glob(pattern):
            class_name = img_path.stem.split("_")[0]
            # 同じクラスの最新ファイル以外は削除
            if class_name in latest_classes and img_path != latest_classes[class_name]:
                try:
                    img_path.unlink()
                except Exception as e:
                    logger.warning(f"ファイル削除エラー: {e}")

    def _cleanup_old_images(self) -> None:
        """古い画像を削除して最大数を維持"""
        pattern = "*.jpg" if self.cropper.format == "jpeg" else "*.png"
        images = sorted(self.cropper.output_dir.glob(pattern))

        while len(images) > self.max_images:
            oldest = images.pop(0)
            try:
                oldest.unlink()
                logger.debug(f"古い画像を削除: {oldest.name}")
            except Exception as e:
                logger.warning(f"ファイル削除エラー: {e}")

    async def close(self) -> None:
        """リソースをクリーンアップ"""
        self.running = False
        self.subscriber.close()
        logger.info(f"ObjectCropperを終了しました。総クロップ数: {self.crop_count}")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="新しいオブジェクトが検出された時にクロップしてAI用画像を生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 新しいオブジェクトが検出された時にクロップ
  uv run python main.py

  # personとtvのみをクロップ
  uv run python main.py --classes person tv

  # オブジェクト追跡の感度を調整
  uv run python main.py --iou-threshold 0.5 --timeout 3.0

  # 利用可能なクラス名:
  person, bicycle, car, motorcycle, airplane, bus, train, truck, boat,
  traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat,
  dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella,
  handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite,
  baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle,
  wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange,
  broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant,
  bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone,
  microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors,
  teddy bear, hair drier, toothbrush
        """,
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="cropped_images",
        help="出力ディレクトリ（デフォルト: cropped_images）",
    )
    parser.add_argument(
        "--classes",
        type=str,
        nargs="+",
        default=None,
        help="クロップ対象のクラス名（例: --classes person tv）指定しない場合は全クラス",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=10,
        help="クロップ時の余白ピクセル（デフォルト: 10）",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=32,
        help="最小クロップサイズ（これより小さいものは無視、デフォルト: 32）",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=90,
        help="JPEG品質 (1-100、デフォルト: 90)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["jpeg", "png"],
        default="jpeg",
        help="出力フォーマット（デフォルト: jpeg）",
    )
    parser.add_argument(
        "--keep-latest",
        action="store_true",
        help="クラスごとに最新の画像のみを保持する",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=100,
        help="保持する最大画像数（0で無制限、デフォルト: 100）",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.3,
        help="同一オブジェクトと判定するIoU閾値（デフォルト: 0.3）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="オブジェクトが消えたと判定する時間（秒、デフォルト: 2.0）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細なログを出力する",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cropper = ObjectCropper(
        output_dir=args.output_dir,
        quality=args.quality,
        format=args.format,
        padding=args.padding,
        min_size=args.min_size,
        target_classes=args.classes,
        keep_latest_only=args.keep_latest,
        max_images=args.max_images,
        iou_threshold=args.iou_threshold,
        object_timeout=args.timeout,
    )

    try:
        asyncio.run(cropper.run())
    except KeyboardInterrupt:
        logger.info("プログラムが中断されました")


if __name__ == "__main__":
    main()
