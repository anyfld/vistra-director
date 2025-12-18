# ObjectCrop

WebRTCMotionDetectionの映像をクロップしてAI用画像を生成するプログラムです。

## 概要

このプログラムは、WebRTCMotionDetectionが処理した映像（物体検知・動体検知の結果が描画されたフレーム）を定期的にクロップし、AI解析用の画像として保存します。

共有メモリを使用してWebRTCMotionDetectionとプロセス間通信を行い、低遅延でフレームを受け取ります。

## 機能

- **共有メモリ連携**: WebRTCMotionDetectionからリアルタイムでフレームを受信
- **定期クロップ**: 設定可能な間隔（デフォルト1秒）でフレームをキャプチャ
- **クロップモード**: 全体画像または中央部分のクロップに対応
- **画像フォーマット**: JPEG/PNG形式での保存に対応
- **自動クリーンアップ**: 古い画像の自動削除機能

## セットアップ

### 前提条件

- Python 3.10以上
- uv (Pythonパッケージマネージャー)

### インストール

```bash
cd poc/ObjectCrop
uv sync
```

## 使い方

### 基本的な使い方

1. まず、WebRTCMotionDetectionを `--share-frame` オプション付きで起動します：

```bash
cd poc/WebRTCMotionDetection
uv run python main.py --share-frame --insecure
```

2. 別のターミナルでObjectCropを起動します：

```bash
cd poc/ObjectCrop
uv run python main.py
```

### コマンドラインオプション

```
usage: main.py [-h] [--interval INTERVAL] [--output-dir OUTPUT_DIR]
               [--crop-mode {full,center}] [--crop-width CROP_WIDTH]
               [--crop-height CROP_HEIGHT] [--quality QUALITY]
               [--format {jpeg,png}] [--keep-latest] [--max-images MAX_IMAGES]
               [--verbose]

オプション:
  --interval INTERVAL   クロップ間隔（秒、デフォルト: 1.0）
  --output-dir OUTPUT_DIR
                        出力ディレクトリ（デフォルト: cropped_images）
  --crop-mode {full,center}
                        クロップモード: full=全体, center=中央部分（デフォルト: full）
  --crop-width CROP_WIDTH
                        クロップ幅（centerモード時、デフォルト: 640）
  --crop-height CROP_HEIGHT
                        クロップ高さ（centerモード時、デフォルト: 480）
  --quality QUALITY     JPEG品質 (1-100、デフォルト: 90)
  --format {jpeg,png}   出力フォーマット（デフォルト: jpeg）
  --keep-latest         最新の画像のみを保持する（古い画像は削除）
  --max-images MAX_IMAGES
                        保持する最大画像数（0で無制限、デフォルト: 100）
  --verbose             詳細なログを出力する
```

### 使用例

#### AI用に最新画像のみを保持（低頻度キャプチャ）

```bash
uv run python main.py --interval 5.0 --keep-latest --quality 85
```

#### 高頻度キャプチャで履歴を保持

```bash
uv run python main.py --interval 0.5 --max-images 200
```

#### 中央部分のみをクロップ

```bash
uv run python main.py --crop-mode center --crop-width 800 --crop-height 600
```

#### PNG形式で保存

```bash
uv run python main.py --format png --output-dir png_captures
```

## アーキテクチャ

```
┌─────────────────────────────────┐
│   WebRTCMotionDetection         │
│   (--share-frame オプション)    │
│                                 │
│   ┌─────────────────────┐       │
│   │ FramePublisher      │       │
│   │ (共有メモリ書き込み) │       │
│   └──────────┬──────────┘       │
└──────────────┼──────────────────┘
               │ 共有メモリ
               │ "webrtc_motion_frame"
               │
┌──────────────┼──────────────────┐
│   ObjectCrop │                  │
│              ▼                  │
│   ┌─────────────────────┐       │
│   │ FrameSubscriber     │       │
│   │ (共有メモリ読み取り) │       │
│   └──────────┬──────────┘       │
│              │                  │
│              ▼                  │
│   ┌─────────────────────┐       │
│   │ ImageCropper        │       │
│   │ (クロップ・保存)     │       │
│   └──────────┬──────────┘       │
│              │                  │
│              ▼                  │
│   cropped_images/               │
│   ├── crop_20241218_123456_001.jpg
│   ├── crop_20241218_123457_002.jpg
│   └── ...                       │
└─────────────────────────────────┘
```

## 共有メモリフォーマット

フレームデータは以下の形式で共有メモリに格納されます：

| オフセット | サイズ | 型 | 説明 |
|-----------|--------|-----|------|
| 0 | 4 | uint32 | 画像幅 |
| 4 | 4 | uint32 | 画像高さ |
| 8 | 4 | uint32 | チャンネル数 |
| 12 | 8 | double | タイムスタンプ |
| 20 | 8 | uint64 | シーケンス番号 |
| 28 | N | bytes | BGRフレームデータ |

## AI連携の例

クロップされた画像は `cropped_images/` ディレクトリに保存されます。
AIに送信する際は、最新の画像を取得して使用できます：

```python
from pathlib import Path

def get_latest_image():
    """最新のクロップ画像を取得"""
    images_dir = Path("cropped_images")
    images = sorted(images_dir.glob("*.jpg"))
    return images[-1] if images else None
```

## トラブルシューティング

### "共有メモリが見つかりません" エラー

WebRTCMotionDetectionが `--share-frame` オプション付きで起動されていることを確認してください。

### フレームが取得できない

1. WebRTCMotionDetectionが正常に動作しているか確認
2. 両プログラムが同じマシンで実行されているか確認
3. `--verbose` オプションで詳細ログを確認

## ライセンス

MIT License
