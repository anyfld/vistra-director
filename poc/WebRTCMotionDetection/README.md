# WebRTC Motion Detection

go2rtcのWebRTC映像を受信してYOLOv8で物体検知・動体検知を行うプログラムです。

## 概要

このプログラムは以下の機能を提供します：

- **WebRTC映像受信**: `aiortc`を使用してWHEP (WebRTC-HTTP Egress Protocol) でgo2rtcからリアルタイム映像を受信
- **物体検知**: Ultralytics YOLOv8を使用した物体検知
- **動体検知**: フレーム間差分を使用した動体検知
- **リアルタイム表示**: OpenCVを使用した検知結果のリアルタイム表示

## 必要要件

- Python 3.10以上
- go2rtcサーバーが稼働していること
- カメラまたはストリームがgo2rtcに設定されていること

## インストール

```bash
# uvを使用する場合
cd poc/WebRTCMotionDetection
uv sync

# pipを使用する場合
pip install -e .
```

## 使用方法

### 基本的な使用方法

```bash
# uvを使用する場合
uv run python main.py --stream <ストリーム名>

# 直接実行する場合
python main.py --stream <ストリーム名>
```

### コマンドライン引数

| 引数 | デフォルト | 説明 |
|------|------------|------|
| `--url` | `https://172.20.10.3` | go2rtcサーバーのベースURL |
| `--stream` | `camera` | go2rtcで設定したストリーム名 |
| `--insecure` | - | SSL証明書の検証をスキップ（自己署名証明書用） |
| `--model` | `yolov8n.pt` | YOLOv8モデル (n/s/m/l/x) |
| `--no-motion` | - | 動体検知を無効にする |
| `--confidence` | `0.5` | 物体検知の信頼度閾値 (0.0-1.0) |
| `--verbose` | - | 詳細なログを出力する |

### 使用例

```bash
# 基本的な使用（デフォルト設定で実行）
uv run python main.py --insecure

# カスタムURLとモデルを指定
uv run python main.py --url https://192.168.1.100 --stream front_camera --model yolov8s.pt --insecure

# 動体検知を無効にして物体検知のみ
uv run python main.py --insecure --no-motion

# 全消し
uv run python main.py --insecure --video-only

# 高い信頼度閾値で検知
uv run python main.py --insecure --confidence 0.7
```

## go2rtcの設定

go2rtcでWebRTCストリームを有効にする設定例：

```yaml
# go2rtc.yaml
streams:
  camera1:
    - rtsp://user:password@192.168.1.100:554/stream

webrtc:
  listen: ":8555"
```

go2rtcのAPIエンドポイント：
- Web UI: `http://localhost:1984/`
- WHEP: `http://localhost:1984/api/webrtc?src=<stream_name>`

## 表示される情報

プログラム実行中、以下の情報が画面上に表示されます：

- **FPS**: 現在のフレームレート
- **Detections**: YOLOv8で検出された物体の数
- **Motion**: 動体検知の有無（Yes/No）
- **バウンディングボックス**: 
  - 緑/その他: YOLOv8による物体検知結果
  - 赤: 動体検知された領域

## キーボード操作

- `q`: プログラムを終了

## 技術詳細

### 使用ライブラリ

- `aiortc`: WebRTC実装（Python）
- `aiohttp`: 非同期HTTPクライアント
- `ultralytics`: YOLOv8モデル
- `opencv-python`: 画像処理・表示
- `numpy`: 数値計算
- `av`: メディアフレーム処理

### アーキテクチャ

```
┌─────────────┐    WHEP    ┌─────────────────────┐
│   go2rtc    │ ─────────> │ WebRTCObjectDetector│
│   Server    │   WebRTC   │                     │
└─────────────┘            │  ┌───────────────┐  │
                           │  │ MotionDetector│  │
                           │  └───────────────┘  │
                           │  ┌───────────────┐  │
                           │  │  YOLO v8      │  │
                           │  └───────────────┘  │
                           │  ┌───────────────┐  │
                           │  │  OpenCV View  │  │
                           │  └───────────────┘  │
                           └─────────────────────┘
```

## トラブルシューティング

### 接続エラー

```
WHEPエンドポイントへの接続に失敗
```

- go2rtcサーバーが起動しているか確認してください
- URLとストリーム名が正しいか確認してください
- ファイアウォールがポートをブロックしていないか確認してください

### フレーム受信タイムアウト

```
フレーム受信タイムアウト
```

- ストリームソース（カメラなど）が正常に動作しているか確認してください
- ネットワーク接続を確認してください

### 低FPS

- より軽量なモデル（`yolov8n.pt`）を使用してください
- GPUが利用可能な環境では自動的にGPUが使用されます

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 関連プロジェクト

- [go2rtc](https://github.com/AlexxIT/go2rtc)
- [aiortc](https://github.com/aiortc/aiortc)
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)
