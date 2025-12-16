"""
Ultralytics YOLOv8を使用した物体検知プログラム
"""
import argparse
from pathlib import Path
from typing import Optional

import cv2
from ultralytics import YOLO


def detect_image(model: YOLO, image_path: str, output_dir: Optional[str] = None) -> None:
    """
    画像ファイルから物体検知を実行

    Args:
        model: YOLOv8モデル
        image_path: 入力画像のパス
        output_dir: 出力ディレクトリ（省略時は入力画像と同じディレクトリ）
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"画像ファイルが見つかりません: {image_path}")

    # 物体検知を実行
    results = model(image_path)

    # 結果を表示
    for result in results:
        # 検知結果を画像に描画
        annotated_frame = result.plot()

        # 検知結果を表示
        print(f"\n検知結果 ({image_path.name}):")
        print(f"検出された物体数: {len(result.boxes)}")
        for box in result.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            class_name = model.names[cls]
            print(f"  - {class_name}: {conf:.2f}")

        # 結果を保存
        if output_dir:
            output_path = Path(output_dir) / f"detected_{image_path.name}"
        else:
            output_path = image_path.parent / f"detected_{image_path.name}"

        cv2.imwrite(str(output_path), annotated_frame)
        print(f"\n検知結果を保存しました: {output_path}")

        # 画像を表示（オプション）
        cv2.imshow("Detection Result", annotated_frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def detect_video(model: YOLO, video_path: str, output_path: Optional[str] = None) -> None:
    """
    動画ファイルから物体検知を実行

    Args:
        model: YOLOv8モデル
        video_path: 入力動画のパス
        output_path: 出力動画のパス（省略時は入力動画と同じディレクトリに保存）
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    # 物体検知を実行
    results = model(str(video_path), save=True)

    if output_path:
        # 結果はmodel()のsave=Trueで保存されるが、カスタムパスが必要な場合
        print(f"検知結果を保存しました: {output_path}")
    else:
        print(f"検知結果を保存しました: runs/detect/predict/")

    print("\n動画の物体検知が完了しました。")


def detect_webcam(model: YOLO, camera_index: int = 0) -> None:
    """
    カメラからのリアルタイム物体検知

    Args:
        model: YOLOv8モデル
        camera_index: カメラのインデックス（デフォルト: 0）
    """
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        raise RuntimeError(f"カメラを開くことができません (index: {camera_index})")

    print("カメラからの物体検知を開始します。'q'キーで終了します。")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("フレームの読み込みに失敗しました")
                break

            # 物体検知を実行
            results = model(frame, verbose=False)

            # 結果を描画
            annotated_frame = results[0].plot()

            # 検知された物体数を表示
            detection_count = len(results[0].boxes)
            cv2.putText(
                annotated_frame,
                f"Detections: {detection_count}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )

            # 画面に表示
            cv2.imshow("YOLOv8 Object Detection", annotated_frame)

            # 'q'キーで終了
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("カメラを閉じました。")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="Ultralytics YOLOv8を使用した物体検知プログラム"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="使用するYOLOv8モデル（yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt）",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="webcam",
        help="入力ソース（画像ファイル、動画ファイル、または 'webcam'、デフォルト: webcam）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="出力パス（省略時は入力ソースと同じディレクトリ）",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="カメラのインデックス（webcam使用時、デフォルト: 0）",
    )

    args = parser.parse_args()

    # モデルをロード
    print(f"モデルをロードしています: {args.model}")
    model = YOLO(args.model)
    print("モデルのロードが完了しました。\n")

    # 入力ソースに応じて処理を分岐
    if args.source.lower() == "webcam":
        detect_webcam(model, args.camera_index)
    else:
        source_path = Path(args.source)
        if not source_path.exists():
            raise FileNotFoundError(f"入力ソースが見つかりません: {args.source}")

        # 拡張子で画像か動画かを判定
        image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

        if source_path.suffix.lower() in image_extensions:
            detect_image(model, str(source_path), args.output)
        elif source_path.suffix.lower() in video_extensions:
            detect_video(model, str(source_path), args.output)
        else:
            raise ValueError(
                f"サポートされていないファイル形式です: {source_path.suffix}\n"
                f"画像形式: {', '.join(image_extensions)}\n"
                f"動画形式: {', '.join(video_extensions)}"
            )


if __name__ == "__main__":
    main()
