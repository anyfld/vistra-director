.PHONY: webrtc-zoom webrtc-zoom-http

webrtc-zoom:
	@IP=$$(ipconfig getifaddr en0 2>/dev/null || echo ""); \
	if [ -z "$${IP}" ]; then \
		echo "PCのIPアドレスを自動取得できませんでした。"; \
		echo "スマホのブラウザで次のURL（PCのIPを置き換え）を開いてください:"; \
		echo "  https://YOUR_PC_IP:8443/broadcast.html"; \
		echo "go2rtc への接続URLはデフォルト (https://localhost) を使用します。"; \
		uv run python WebRTCZoom/main.py --insecure; \
	else \
		echo "スマホのブラウザで次のURLを開いてください:"; \
		echo "  https://$${IP}:8443/broadcast.html"; \
		uv run python WebRTCZoom/main.py --insecure --url https://$${IP}; \
	fi

webrtc-zoom-http:
	uv run python WebRTCZoom/main.py --http --no-browser
