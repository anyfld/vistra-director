"""
WebRTC Camera Zoom Viewer サーバー

go2rtcの映像をズームイン/アウトできるWebビューアを提供するHTTPSサーバー。
Media Capture and Stream APIとWebRTC (WHEP)を使用して映像を受信し、
go2rtcのPTZ APIを使用して配信元カメラのズームを制御します。

WHEPプロキシ機能により、CORSや証明書の問題を回避します。
"""

import argparse
import json
import logging
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, ClassVar


# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class WHEPProxyHandler(SimpleHTTPRequestHandler):
    """WHEPプロキシ機能付きHTTPリクエストハンドラー"""

    # クラス変数としてサーバー設定を保持
    serve_directory: ClassVar[str | None] = None
    go2rtc_url: ClassVar[str] = ""
    insecure: ClassVar[bool] = False

    # ズームコマンドキュー（ストリーム名 -> コマンドリスト）
    zoom_commands: ClassVar[dict[str, list[dict[str, Any]]]] = {}
    # SSE接続（ストリーム名 -> 接続ハンドラーリスト）
    sse_clients: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=self.serve_directory, **kwargs)

    def end_headers(self) -> None:
        # CORSヘッダーを追加
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        """OPTIONSリクエストの処理（プリフライトリクエスト対応）"""
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        """GETリクエストの処理"""
        # /api/config - サーバー設定を返す
        if self.path == "/api/config":
            self._handle_config()
            return
        # /api/zoom/poll - ズームコマンドをポーリング（配信側用・フォールバック）
        if self.path.startswith("/api/zoom/poll"):
            self._handle_zoom_poll()
            return
        # /api/zoom/stream - SSEでズームコマンドをリアルタイム受信（配信側用）
        if self.path.startswith("/api/zoom/stream"):
            self._handle_zoom_sse()
            return
        # 静的ファイルの配信
        super().do_GET()

    def do_POST(self) -> None:
        """POSTリクエストの処理"""
        # /api/whep - WHEPプロキシ（視聴側）
        if self.path.startswith("/api/whep"):
            self._handle_whep_proxy()
            return
        # /api/webrtc - WHIP/WHEPプロキシ（配信側/視聴側両方）
        if self.path.startswith("/api/webrtc"):
            self._handle_webrtc_proxy()
            return
        # /api/ptz - PTZコマンドプロキシ
        if self.path.startswith("/api/ptz"):
            self._handle_ptz_proxy()
            return
        # /api/zoom/command - ズームコマンド送信（受信側から配信側へ）
        if self.path.startswith("/api/zoom/command"):
            self._handle_zoom_command()
            return
        self.send_error(404, "Not Found")

    def _handle_config(self) -> None:
        """サーバー設定を返す"""
        config = {
            "go2rtc_url": self.go2rtc_url,
            "proxy_enabled": True,
        }
        response = json.dumps(config).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _handle_zoom_command(self) -> None:
        """受信側からのズームコマンドを受け付ける"""
        # クエリパラメータを解析
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]

        params = {}
        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                params[key] = urllib.parse.unquote(value)

        stream_name = params.get("stream", "camera")
        cmd = params.get("cmd", "")
        value = params.get("value", "")

        if not cmd:
            self.send_error(400, "Missing cmd parameter")
            return

        logger.info(f"ズームコマンド受信: stream={stream_name}, cmd={cmd}, value={value}")

        command_data: dict[str, Any] = {
            "cmd": cmd,
            "value": value,
            "timestamp": time.time(),
        }

        # SSEクライアントに即座に送信
        sent_via_sse = False
        if stream_name in WHEPProxyHandler.sse_clients:
            clients_to_remove = []
            for client in WHEPProxyHandler.sse_clients[stream_name]:
                try:
                    event_data = f"event: zoom\ndata: {json.dumps(command_data)}\n\n"
                    client.wfile.write(event_data.encode("utf-8"))
                    client.wfile.flush()
                    sent_via_sse = True
                    logger.info(f"SSEでコマンド送信成功: {cmd}")
                except Exception as e:
                    logger.warning(f"SSE送信エラー: {e}")
                    clients_to_remove.append(client)
            
            # 切断されたクライアントを削除
            for client in clients_to_remove:
                WHEPProxyHandler.sse_clients[stream_name].remove(client)

        # SSEで送信できなかった場合はキューに追加（ポーリング用フォールバック）
        if not sent_via_sse:
            if stream_name not in WHEPProxyHandler.zoom_commands:
                WHEPProxyHandler.zoom_commands[stream_name] = []
            WHEPProxyHandler.zoom_commands[stream_name].append(command_data)

            # 古いコマンドを削除（5秒以上前）
            current_time = time.time()
            WHEPProxyHandler.zoom_commands[stream_name] = [
                c for c in WHEPProxyHandler.zoom_commands[stream_name]
                if current_time - c["timestamp"] < 5
            ]

        response = json.dumps({"status": "ok", "sse": sent_via_sse}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _handle_zoom_poll(self) -> None:
        """配信側がズームコマンドをポーリングする（フォールバック用）"""
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]

        params = {}
        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                params[key] = urllib.parse.unquote(value)

        stream_name = params.get("stream", "camera")

        commands = WHEPProxyHandler.zoom_commands.get(stream_name, [])
        WHEPProxyHandler.zoom_commands[stream_name] = []

        response = json.dumps({"commands": commands}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _handle_zoom_sse(self) -> None:
        """SSEでズームコマンドをリアルタイム配信"""
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]

        params = {}
        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                params[key] = urllib.parse.unquote(value)

        stream_name = params.get("stream", "camera")
        
        logger.info(f"SSE接続開始: stream={stream_name}")

        # SSEヘッダーを送信
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # クライアントリストに追加
        if stream_name not in WHEPProxyHandler.sse_clients:
            WHEPProxyHandler.sse_clients[stream_name] = []
        WHEPProxyHandler.sse_clients[stream_name].append(self)

        # 接続確認イベントを送信
        try:
            self.wfile.write(b"event: connected\ndata: {\"status\":\"ok\"}\n\n")
            self.wfile.flush()
        except Exception:
            pass

        # 接続を維持（クライアントが切断するまで）
        try:
            while True:
                time.sleep(30)  # キープアライブ
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except Exception:
                    break
        except Exception:
            pass
        finally:
            # クライアントリストから削除
            if stream_name in WHEPProxyHandler.sse_clients:
                if self in WHEPProxyHandler.sse_clients[stream_name]:
                    WHEPProxyHandler.sse_clients[stream_name].remove(self)
            logger.info(f"SSE接続終了: stream={stream_name}")

    def _handle_whep_proxy(self) -> None:
        """WHEPリクエストをgo2rtcにプロキシ"""
        self._handle_webrtc_proxy()

    def _handle_webrtc_proxy(self) -> None:
        """WebRTC (WHIP/WHEP)リクエストをgo2rtcにプロキシ"""
        # クエリパラメータからストリーム名を取得
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]

        # リクエストボディ（SDP）を読み取り
        content_length = int(self.headers.get("Content-Length", 0))
        sdp_offer = self.rfile.read(content_length)

        # go2rtcのWebRTCエンドポイントURL
        go2rtc_url = f"{self.go2rtc_url}/api/webrtc"
        if query:
            go2rtc_url += f"?{query}"

        logger.info(f"WebRTCプロキシ: {go2rtc_url}")

        try:
            # SSL設定（自己署名証明書対応）
            ssl_context = None
            if self.insecure:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            # go2rtcにリクエストを転送
            req = urllib.request.Request(
                go2rtc_url,
                data=sdp_offer,
                headers={"Content-Type": "application/sdp"},
                method="POST",
            )

            with urllib.request.urlopen(req, context=ssl_context, timeout=10) as resp:
                sdp_answer = resp.read()
                status_code = resp.status

            # レスポンスを返す
            self.send_response(status_code)
            self.send_header("Content-Type", "application/sdp")
            self.send_header("Content-Length", str(len(sdp_answer)))
            self.end_headers()
            self.wfile.write(sdp_answer)
            logger.info(f"WebRTCプロキシ成功: {status_code}")

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"WebRTCプロキシエラー: {e.code} - {error_body}")
            self.send_error(e.code, error_body)
        except urllib.error.URLError as e:
            logger.error(f"WebRTCプロキシ接続エラー: {e.reason}")
            self.send_error(502, f"Bad Gateway: {e.reason}")
        except Exception as e:
            logger.error(f"WebRTCプロキシ例外: {e}")
            self.send_error(500, str(e))

    def _handle_ptz_proxy(self) -> None:
        """PTZコマンドをgo2rtcにプロキシ（WebSocket経由）"""
        # クエリパラメータを解析
        # /api/ptz?src=camera&cmd=zoom_in
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]

        params = {}
        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                params[key] = urllib.parse.unquote(value)

        stream_name = params.get("src", "camera")
        ptz_cmd = params.get("cmd", "")

        if not ptz_cmd:
            self.send_error(400, "Missing cmd parameter")
            return

        logger.info(f"PTZコマンド: stream={stream_name}, cmd={ptz_cmd}")

        try:
            # go2rtcのWebSocket APIにPTZコマンドを送信
            # WebSocketを使う代わりに、HTTP経由でWebSocket風のメッセージを送信
            # go2rtcはHTTP POSTでもPTZコマンドを受け付ける場合がある
            
            # まず、go2rtcのストリーム情報を取得してWebSocket URLを構築
            # 実際にはWebSocketライブラリを使う必要があるが、
            # シンプルにするためにwebsocketモジュールを動的にインポート
            
            success = self._send_ptz_via_websocket(stream_name, ptz_cmd)
            
            if success:
                response = json.dumps({"status": "ok", "cmd": ptz_cmd}).encode("utf-8")
                self.send_response(200)
            else:
                response = json.dumps({"status": "error", "message": "PTZ command failed"}).encode("utf-8")
                self.send_response(500)
            
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        except Exception as e:
            logger.error(f"PTZプロキシ例外: {e}")
            self.send_error(500, str(e))

    def _send_ptz_via_websocket(self, stream_name: str, ptz_cmd: str) -> bool:
        """WebSocket経由でPTZコマンドを送信"""
        try:
            import websocket  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("websocket-clientがインストールされていません。pip install websocket-client を実行してください。")
            # フォールバック: HTTP POSTを試す
            return self._send_ptz_via_http(stream_name, ptz_cmd)

        # WebSocket URLを構築
        ws_url = self.go2rtc_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/api/ws?src={stream_name}"

        logger.info(f"PTZ WebSocket接続: {ws_url}")

        try:
            # SSL設定
            sslopt: dict[str, Any] = {}
            if self.insecure:
                sslopt = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}

            # WebSocket接続
            ws = websocket.create_connection(
                ws_url,
                timeout=5,
                sslopt=sslopt,
            )

            # PTZコマンドを送信
            # go2rtcのPTZコマンド形式: {"type":"ptz","value":"zoom_in"}
            ptz_message = json.dumps({"type": "ptz", "value": ptz_cmd})
            ws.send(ptz_message)
            logger.info(f"PTZコマンド送信: {ptz_message}")

            # 応答を待つ（オプション）
            try:
                ws.settimeout(1)
                response = ws.recv()
                logger.info(f"PTZ応答: {response}")
            except websocket.WebSocketTimeoutException:
                pass  # タイムアウトは無視

            ws.close()
            return True

        except Exception as e:
            logger.error(f"PTZ WebSocketエラー: {e}")
            return False

    def _send_ptz_via_http(self, stream_name: str, ptz_cmd: str) -> bool:
        """HTTP POST経由でPTZコマンドを送信（フォールバック）"""
        # go2rtcの一部バージョンではHTTP APIでPTZを受け付ける
        ptz_url = f"{self.go2rtc_url}/api/ptz?src={stream_name}&cmd={ptz_cmd}"
        
        logger.info(f"PTZ HTTPリクエスト: {ptz_url}")

        try:
            ssl_context = None
            if self.insecure:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(ptz_url, method="POST")
            with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
                logger.info(f"PTZ HTTP応答: {resp.status}")
                return resp.status == 200

        except Exception as e:
            logger.warning(f"PTZ HTTPエラー（WebSocket未対応の可能性）: {e}")
            return False


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """マルチスレッド対応HTTPServer（SSE等の長時間接続をサポート）"""
    daemon_threads = True


def generate_self_signed_cert() -> tuple[str, str]:
    """
    自己署名証明書を生成する

    Returns:
        tuple[str, str]: (証明書ファイルパス, 秘密鍵ファイルパス)
    """
    import tempfile

    cert_dir = tempfile.mkdtemp()
    cert_path = Path(cert_dir) / "cert.pem"
    key_path = Path(cert_dir) / "key.pem"

    # OpenSSLコマンドで自己署名証明書を生成
    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        "365",
        "-nodes",
        "-subj",
        "/CN=localhost",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"自己署名証明書を生成しました: {cert_path}")
        return str(cert_path), str(key_path)
    except subprocess.CalledProcessError as e:
        logger.error(f"証明書生成に失敗: {e.stderr.decode()}")
        raise RuntimeError("OpenSSLによる証明書生成に失敗しました")
    except FileNotFoundError:
        raise RuntimeError("opensslコマンドが見つかりません。OpenSSLをインストールしてください。")


def run_server(
    port: int = 8443,
    use_https: bool = True,
    open_browser: bool = True,
    cert_file: str | None = None,
    key_file: str | None = None,
    go2rtc_url: str = "https://172.20.10.3",
    insecure: bool = False,
) -> None:
    """
    Webサーバーを起動する

    Args:
        port: サーバーポート番号
        use_https: HTTPSを使用するか
        open_browser: ブラウザを自動で開くか
        cert_file: SSL証明書ファイルパス（指定しない場合は自動生成）
        key_file: SSL秘密鍵ファイルパス（指定しない場合は自動生成）
        go2rtc_url: go2rtcサーバーのベースURL
        insecure: SSL証明書の検証をスキップするか
    """
    # サーバーディレクトリを設定（このスクリプトと同じディレクトリ）
    serve_dir = str(Path(__file__).parent)

    # ハンドラークラスの設定
    WHEPProxyHandler.serve_directory = serve_dir
    WHEPProxyHandler.go2rtc_url = go2rtc_url.rstrip("/")
    WHEPProxyHandler.insecure = insecure

    server = ThreadingHTTPServer(("0.0.0.0", port), WHEPProxyHandler)

    protocol = "http"
    if use_https:
        # SSL証明書の準備
        if cert_file and key_file:
            logger.info(f"指定された証明書を使用: {cert_file}")
        else:
            cert_file, key_file = generate_self_signed_cert()

        # SSLコンテキストを設定
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert_file, key_file)
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
        protocol = "https"

    url = f"{protocol}://localhost:{port}/"
    logger.info("=" * 60)
    logger.info("WebRTC Camera Zoom Viewer サーバーを起動しました")
    logger.info(f"URL: {url}")
    logger.info(f"go2rtc: {go2rtc_url} (プロキシ経由)")
    if insecure:
        logger.info("SSL検証: 無効（自己署名証明書対応）")
    logger.info("=" * 60)

    if use_https:
        logger.warning(
            "⚠️  自己署名証明書を使用しているため、ブラウザで警告が表示されます。"
        )
        logger.warning("   「詳細設定」→「localhost にアクセスする」で続行してください。")

    logger.info("\n操作方法:")
    logger.info("  🔍 ズームボタン: 配信元カメラのズームイン/アウト")
    logger.info("  🖱️  マウスホイール: デジタルズーム（表示のみ）")
    logger.info("  👆 ピンチ操作: タッチデバイスでのデジタルズーム")
    logger.info("  ✋ ドラッグ: パン（表示位置移動）")
    logger.info("  ⌨️  キーボード: +/- でカメラズーム、矢印キーでパン")
    logger.info("\n終了するには Ctrl+C を押してください。\n")

    # ブラウザを開く
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"ブラウザを開けませんでした: {e}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nサーバーを停止しました")
    finally:
        server.server_close()


def main() -> None:
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="WebRTC Camera Zoom Viewer - go2rtcの映像をズーム表示するWebサーバー"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="サーバーポート番号（デフォルト: 8443）",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="HTTPモードで起動（HTTPSの代わりに）※ ローカルホストでのみ動作",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="ブラウザを自動で開かない",
    )
    parser.add_argument(
        "--cert",
        type=str,
        help="SSL証明書ファイルパス（オプション）",
    )
    parser.add_argument(
        "--key",
        type=str,
        help="SSL秘密鍵ファイルパス（オプション）",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="https://172.20.10.3",
        help="go2rtcサーバーのベースURL（デフォルト: https://172.20.10.3）",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="SSL証明書の検証をスキップする（自己署名証明書用）",
    )

    args = parser.parse_args()

    run_server(
        port=args.port,
        use_https=not args.http,
        open_browser=not args.no_browser,
        cert_file=args.cert,
        key_file=args.key,
        go2rtc_url=args.url,
        insecure=args.insecure,
    )


if __name__ == "__main__":
    main()

