# Object Detection with Ultralytics YOLOv8

Ultralytics YOLOv8を使用した物体検知プログラムです。

## 前提条件

- [uv](https://github.com/astral-sh/uv) がインストールされていること

## インストール

```bash
# 依存関係のインストール
uv sync
```

## 使用方法

### 画像からの物体検知

```bash
uv run python main.py --source image.jpg
```

### カメラからのリアルタイム検知

```bash
uv run python main.py --source 0
```

### ビデオファイルからの検知

```bash
uv run python main.py --source video.mp4
```

### モデルの選択

デフォルトでは`yolov8n.pt`（nano、最も軽量）が使用されます。より高精度なモデルを指定できます：

- `yolov8n.pt` - Nano（最速、軽量）
- `yolov8s.pt` - Small
- `yolov8m.pt` - Medium
- `yolov8l.pt` - Large
- `yolov8x.pt` - XLarge（最高精度、最も重い）

```bash
uv run python main.py --source image.jpg --model yolov8m.pt
```

### 結果の保存先を指定

```bash
uv run python main.py --source image.jpg --save-dir output
```

## 機能

- 画像ファイルからの物体検知
- カメラからのリアルタイム物体検知
- ビデオファイルからの物体検知
- 検知結果の可視化
- 複数のYOLOv8モデルサイズに対応

## 検知結果

画像やビデオの検知結果は、デフォルトで`runs/detect`ディレクトリに保存されます。カメラからの検知はリアルタイムで画面に表示されます（'q'キーで終了）。

