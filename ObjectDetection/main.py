"""
Ultralytics YOLOv8を使用した物体検知プログラム

使用方法:
    # 画像から検知
    python main.py --source image.jpg
    
    # カメラからリアルタイム検知
    python main.py --source 0
    
    # ビデオファイルから検知
    python main.py --source video.mp4
"""
import argparse
from pathlib import Path
from ultralytics import YOLO
import cv2


def detect_image(model: YOLO, source: str, save_dir: str = "runs/detect") -> None:
    """
    画像ファイルから物体を検知します。
    
    Args:
        model: YOLOv8モデル
        source: 画像ファイルのパス
        save_dir: 結果を保存するディレクトリ
    """
    results = model(source, save=True, project=save_dir)
    
    for r in results:
        print(f"\n検知された物体数: {len(r.boxes)}")
        for box in r.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            label = model.names[cls]
            print(f"  - {label}: {conf:.2%}")


def detect_camera(model: YOLO, camera_id: int = 0) -> None:
    """
    カメラからのリアルタイム物体検知を行います。
    
    Args:
        model: YOLOv8モデル
        camera_id: カメラデバイスID（通常は0）
    """
    cap = cv2.VideoCapture(camera_id)
    
    if not cap.isOpened():
        print(f"エラー: カメラID {camera_id} を開けませんでした")
        return
    
    print("カメラからの検知を開始します。'q'キーで終了します。")
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("フレームを読み込めませんでした")
                break
            
            # YOLOv8で検知
            results = model(frame, verbose=False)
            
            # 結果をフレームに描画
            annotated_frame = results[0].plot()
            
            # 検知結果を表示
            cv2.imshow("YOLOv8 Object Detection", annotated_frame)
            
            # 'q'キーで終了
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    
    finally:
        cap.release()
        cv2.destroyAllWindows()


def detect_video(model: YOLO, source: str, save_dir: str = "runs/detect") -> None:
    """
    ビデオファイルから物体を検知します。
    
    Args:
        model: YOLOv8モデル
        source: ビデオファイルのパス
        save_dir: 結果を保存するディレクトリ
    """
    results = model(source, save=True, project=save_dir)
    
    # 検知結果のサマリーを表示
    for r in results:
        print(f"\n検知された物体数: {len(r.boxes)}")
        if len(r.boxes) > 0:
            print("検知された物体:")
            for box in r.boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                label = model.names[cls]
                print(f"  - {label}: {conf:.2%}")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="Ultralytics YOLOv8を使用した物体検知プログラム"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="0",
        help="入力ソース（画像パス、ビデオパス、またはカメラID）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="使用するYOLOv8モデル（yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt）",
    )
    parser.add_argument(
        "--save-dir",
        type=str,
        default="runs/detect",
        help="結果を保存するディレクトリ",
    )
    
    args = parser.parse_args()
    
    # モデルを読み込み
    print(f"モデル '{args.model}' を読み込んでいます...")
    model = YOLO(args.model)
    print("モデルの読み込みが完了しました。\n")
    
    source_path = Path(args.source)
    
    # ソースタイプを判定
    if args.source.isdigit():
        # カメラID
        detect_camera(model, int(args.source))
    elif source_path.exists() and source_path.is_file():
        # ファイル
        ext = source_path.suffix.lower()
        if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']:
            detect_image(model, args.source, args.save_dir)
        elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv']:
            detect_video(model, args.source, args.save_dir)
        else:
            print(f"サポートされていないファイル形式: {ext}")
    else:
        print(f"エラー: ソース '{args.source}' が見つかりません")
        return
    
    print("\n処理が完了しました。")


if __name__ == "__main__":
    main()
