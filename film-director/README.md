# Film Director

カメラ登録とPTZ制御を行うツールです。

## セットアップ

```bash
# 依存関係のインストール
cd film-director
uv sync
```

## Makefileを使った使用方法

### 基本的な使い方

```bash
# 必須パラメータのみ
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001"

# アドレスを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" ADDRESS="192.168.1.100"

# サービスURLを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" URL="http://example.com:8080"
```

### 接続タイプの指定

```bash
# WebRTC接続（デフォルト）
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" CONNECTION_TYPE="WEBRTC"

# ONVIF接続
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" CONNECTION_TYPE="ONVIF" PORT="8080"

# RTSP接続
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" CONNECTION_TYPE="RTSP" ADDRESS="rtsp://example.com/stream"
```

### 認証情報の指定

```bash
# ユーザー名とパスワード
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" USERNAME="admin" PASSWORD="password"

# トークン認証
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" TOKEN="your-token"
```

### PTZ制御の設定

```bash
# PTZを無効化
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" NO_PTZ=1

# 仮想PTZモード（ハードウェア制御なし）
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" VIRTUAL_PTZ=1

# 仮想PTZモードでGUIポートを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" VIRTUAL_PTZ=1 VIRTUAL_PTZ_GUI_PORT=8888

# PTZサービスURLを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" PTZ_SERVICE_URL="http://ptz-service:8080"
```

### PTZ補正機能

カメラの向きが実際の向きと異なる場合に使用します。

```bash
# パンとチルトを入れ替え
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" PTZ_SWAP_PAN_TILT=1

# パンを反転
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" PTZ_INVERT_PAN=1

# チルトを反転
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" PTZ_INVERT_TILT=1

# 複数の補正を組み合わせる
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" \
  PTZ_SWAP_PAN_TILT=1 PTZ_INVERT_PAN=1 PTZ_INVERT_TILT=1
```

### その他のオプション

```bash
# 詳細ログを出力
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" VERBOSE=1

# TLS証明書の検証をスキップ
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" INSECURE=1

# メタデータを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" \
  METADATA="location=room1" METADATA="type=indoor"

# WebRTC接続名を指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" WEBRTC_CONNECTION_NAME="camera1"

# カメラモードを指定
make register-camera NAME="カメラ1" MASTER_MF_ID="mf-001" MODE="LIGHTWEIGHT"
```

### 完全な例

```bash
make register-camera \
  NAME="会議室カメラ" \
  MASTER_MF_ID="mf-001" \
  ADDRESS="192.168.1.100" \
  CONNECTION_TYPE="WEBRTC" \
  URL="http://localhost:8080" \
  PTZ_SERVICE_URL="http://localhost:8080" \
  VIRTUAL_PTZ=1 \
  VIRTUAL_PTZ_GUI_PORT=8888 \
  PTZ_SWAP_PAN_TILT=1 \
  PTZ_INVERT_PAN=1 \
  VERBOSE=1
```

## テスト

```bash
make test
```
