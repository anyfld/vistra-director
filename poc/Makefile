.PHONY: webrtc-zoom webrtc-zoom-http

webrtc-zoom:
	@IP=$$(ipconfig getifaddr en0 2>/dev/null || echo "YOUR_PC_IP")
	@echo "スマホのブラウザで次のURLを開いてください:"
	@echo "  https://$${IP}:8443/broadcast.html"
	uv run python WebRTCZoom/main.py --insecure --url https://$${IP}

webrtc-zoom-http:
	uv run python WebRTCZoom/main.py --http --no-browser
