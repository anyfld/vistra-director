#!/usr/bin/env python3
"""
WebRTCZoom ズームコントロール CLI

配信中のカメラのズームをコマンドラインから操作するツールです。

使用例:
    # ズームイン（デフォルト0.5倍）
    uv run python WebRTCZoom/zoom_control.py zoom_in

    # ズームアウト
    uv run python WebRTCZoom/zoom_control.py zoom_out

    # 倍率を指定してズームイン（1.0倍ずつ）
    uv run python WebRTCZoom/zoom_control.py zoom_in --value 1.0

    # 絶対値でズームを設定（3.0倍に設定）
    uv run python WebRTCZoom/zoom_control.py set --value 3.0

    # ストリーム名を指定
    uv run python WebRTCZoom/zoom_control.py zoom_in --stream my_camera

    # サーバーURLを指定
    uv run python WebRTCZoom/zoom_control.py zoom_in --server https://192.168.1.100:8443
"""

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal


ZoomCommand = Literal["zoom_in", "zoom_out", "set_zoom"]


def send_zoom_command(
    cmd: ZoomCommand,
    stream: str = "camera",
    server_url: str = "https://localhost:8443",
    insecure: bool = True,
    value: float | None = None,
) -> bool:
    """
    ズームコマンドをサーバーに送信する

    Args:
        cmd: ズームコマンド ("zoom_in", "zoom_out", "set_zoom")
        stream: ストリーム名
        server_url: WebRTCZoomサーバーのURL
        insecure: SSL証明書の検証をスキップするか
        value: ズーム倍率（zoom_in/zoom_outは増減値、set_zoomは絶対値）

    Returns:
        bool: 成功した場合True
    """
    # URLを構築
    params: dict[str, str | float] = {"stream": stream, "cmd": cmd}
    if value is not None:
        params["value"] = value
    url = f"{server_url.rstrip('/')}/api/zoom/command?{urllib.parse.urlencode(params)}"

    # SSL設定
    ssl_context = None
    if insecure:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except urllib.error.HTTPError as e:
        print(f"エラー: HTTP {e.code} - {e.reason}", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"接続エラー: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        return False


def zoom_in(
    stream: str = "camera",
    server_url: str = "https://localhost:8443",
    insecure: bool = True,
    value: float = 0.5,
) -> bool:
    """
    ズームイン

    Args:
        stream: ストリーム名
        server_url: サーバーURL
        insecure: SSL証明書検証をスキップ
        value: ズーム増加量（デフォルト: 0.5）
    """
    return send_zoom_command("zoom_in", stream, server_url, insecure, value)


def zoom_out(
    stream: str = "camera",
    server_url: str = "https://localhost:8443",
    insecure: bool = True,
    value: float = 0.5,
) -> bool:
    """
    ズームアウト

    Args:
        stream: ストリーム名
        server_url: サーバーURL
        insecure: SSL証明書検証をスキップ
        value: ズーム減少量（デフォルト: 0.5）
    """
    return send_zoom_command("zoom_out", stream, server_url, insecure, value)


def set_zoom(
    zoom_level: float,
    stream: str = "camera",
    server_url: str = "https://localhost:8443",
    insecure: bool = True,
) -> bool:
    """
    ズーム倍率を絶対値で設定

    Args:
        zoom_level: 設定するズーム倍率
        stream: ストリーム名
        server_url: サーバーURL
        insecure: SSL証明書検証をスキップ
    """
    return send_zoom_command("set_zoom", stream, server_url, insecure, zoom_level)


def main() -> None:
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="WebRTCZoom ズームコントロール - 配信カメラのズームを操作",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # ズームイン（デフォルト0.5倍）
  %(prog)s zoom_in

  # 倍率を指定してズームイン（1.0倍ずつ）
  %(prog)s zoom_in --value 1.0

  # 絶対値でズーム設定（3.0倍に設定）
  %(prog)s set --value 3.0

  # ズームアウト  
  %(prog)s zoom_out

  # ストリーム名を指定
  %(prog)s zoom_in --stream my_camera

  # サーバーURLを指定（リモートサーバー）
  %(prog)s zoom_in --server https://192.168.1.100:8443
        """,
    )

    parser.add_argument(
        "command",
        choices=["zoom_in", "zoom_out", "set", "in", "out", "+", "-"],
        help="ズームコマンド: zoom_in/in/+ (ズームイン), zoom_out/out/- (ズームアウト), set (絶対値設定)",
    )

    parser.add_argument(
        "--stream",
        "-s",
        type=str,
        default="camera",
        help="ストリーム名（デフォルト: camera）",
    )

    parser.add_argument(
        "--server",
        "-u",
        type=str,
        default="https://localhost:8443",
        help="WebRTCZoomサーバーのURL（デフォルト: https://localhost:8443）",
    )

    parser.add_argument(
        "--no-insecure",
        action="store_true",
        help="SSL証明書の検証を行う（デフォルトはスキップ）",
    )

    parser.add_argument(
        "--value",
        "-v",
        type=float,
        default=None,
        help="ズーム倍率（zoom_in/outは増減値、setは絶対値）",
    )

    parser.add_argument(
        "--repeat",
        "-r",
        type=int,
        default=1,
        help="コマンドを繰り返す回数（デフォルト: 1）",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="出力を抑制する",
    )

    args = parser.parse_args()

    # コマンドを正規化
    if args.command in ("zoom_in", "in", "+"):
        cmd: ZoomCommand = "zoom_in"
        cmd_name = "ズームイン"
        value = args.value if args.value is not None else 0.5
    elif args.command in ("zoom_out", "out", "-"):
        cmd = "zoom_out"
        cmd_name = "ズームアウト"
        value = args.value if args.value is not None else 0.5
    else:  # set
        cmd = "set_zoom"
        cmd_name = "ズーム設定"
        if args.value is None:
            print(
                "エラー: setコマンドには --value オプションが必要です", file=sys.stderr
            )
            sys.exit(1)
        value = args.value

    insecure = not args.no_insecure

    # コマンドを実行
    success_count = 0
    for i in range(args.repeat):
        success = send_zoom_command(cmd, args.stream, args.server, insecure, value)
        if success:
            success_count += 1
            if not args.quiet:
                if args.repeat > 1:
                    print(f"✓ {cmd_name} ({value}x) ({i + 1}/{args.repeat})")
                else:
                    print(f"✓ {cmd_name} ({value}x)")
        else:
            if not args.quiet:
                print(f"✗ {cmd_name}に失敗しました", file=sys.stderr)

    # 終了コード
    if success_count == args.repeat:
        sys.exit(0)
    elif success_count > 0:
        sys.exit(1)  # 部分的成功
    else:
        sys.exit(2)  # 完全失敗


if __name__ == "__main__":
    main()
