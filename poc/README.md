# POC (Proof of Concept)

映像解析システムのPOCプログラム群です。

## プロジェクト構成

```
poc/
├── run_all.py              # 統合ランチャー（Python版）
├── run_all.sh              # 統合ランチャー（シェルスクリプト版）
├── WebRTCMotionDetection/  # WebRTC映像受信 + 物体検知 + 動体検知
└── ObjectCrop/             # 映像クロップ（AI用画像生成）
```

## クイックスタート

### 前提条件

- Python 3.10以上
- uv (Pythonパッケージマネージャー)
- go2rtcサーバーが稼働していること

### セットアップ

```bash
cd poc

# 各プロジェクトの依存関係をインストール
cd WebRTCMotionDetection && uv sync && cd ..
cd ObjectCrop && uv sync && cd ..
```

### 統合起動（推奨）

すべてのプログラムを一度に起動できます：

```bash
# uv で実行（推奨）
uv run python run_all.py --insecure

# または シェルスクリプト版
./run_all.sh --insecure
```

### 主要オプション

```bash
# 基本的な起動
uv run python run_all.py --insecure

# 田中おすすめのコマンド
uv run python run_all.py --insecure --no-motion --manual-crop-label --classes person

# カスタムgo2rtcサーバーを指定
uv run python run_all.py --insecure --url https://192.168.1.100 --stream front_camera

# 映像のみ（検知なし）で高速クロップ
uv run python run_all.py --insecure --video-only --interval 0.5

# 最新画像のみ保持（AI連携用）
uv run python run_all.py --insecure --keep-latest --interval 2.0

# すべてのオプションを確認
uv run python run_all.py --help
```

## 個別起動

各プログラムを個別に起動することも可能です：

### ターミナル1: WebRTCMotionDetection

```bash
cd WebRTCMotionDetection
uv run python main.py --insecure --share-frame
```

### ターミナル2: ObjectCrop

```bash
cd ObjectCrop
uv run python main.py --interval 1.0 --keep-latest
```

## データフロー

```
go2rtc Server
     │
     │ WebRTC (WHEP)
     ▼
┌─────────────────────────────────┐
│   WebRTCMotionDetection         │
│   ├── 物体検知 (YOLOv8)         │
│   ├── 動体検知                  │
│   └── 映像表示                  │
└──────────────┬──────────────────┘
               │ 共有メモリ
               ▼
┌─────────────────────────────────┐
│   ObjectCrop                    │
│   ├── 定期クロップ              │
│   └── 画像保存                  │
└──────────────┬──────────────────┘
               │
               ▼
        cropped_images/
        ├── crop_xxx_001.jpg
        ├── crop_xxx_002.jpg
        └── ...
               │
               ▼
         AI解析システム
```

## 出力

クロップされた画像は `ObjectCrop/cropped_images/` に保存されます。
AI解析システムはこのディレクトリから最新画像を取得して処理できます。

## 各プロジェクトの詳細

- [WebRTCMotionDetection/README.md](WebRTCMotionDetection/README.md)
- [ObjectCrop/README.md](ObjectCrop/README.md)

## トラブルシューティング

### "共有メモリが見つかりません" エラー

WebRTCMotionDetectionが `--share-frame` オプション付きで起動されていることを確認してください。

### go2rtcに接続できない

1. go2rtcサーバーが起動しているか確認
2. `--url` オプションで正しいURLを指定
3. 自己署名証明書の場合は `--insecure` を追加

### フレームが取得できない

1. カメラ/ストリームが正常に動作しているか確認
2. `--verbose` オプションで詳細ログを確認
