.PHONY: register-camera test

register-camera:
	@if [ -z "$(NAME)" ] || [ -z "$(MASTER_MF_ID)" ] || [ -z "$(ADDRESS)" ]; then \
		echo "エラー: NAME, MASTER_MF_ID, ADDRESS は必須です"; \
		echo "使用例: make register-camera NAME=\"カメラ1\" MASTER_MF_ID=\"mf-001\" ADDRESS=\"192.168.1.100\""; \
		exit 1; \
	fi
	cd film-director && uv run python main.py \
		--name "$(NAME)" \
		--master-mf-id "$(MASTER_MF_ID)" \
		--address "$(ADDRESS)" \
		--url "$(if $(URL),$(URL),http://localhost:8080)" \
		$(if $(MODE),--mode $(MODE),) \
		$(if $(CONNECTION_TYPE),--connection-type $(CONNECTION_TYPE),) \
		$(if $(PORT),--port $(PORT),) \
		$(if $(USERNAME),--username $(USERNAME),) \
		$(if $(PASSWORD),--password $(PASSWORD),) \
		$(if $(TOKEN),--token $(TOKEN),) \
		$(if $(SUPPORTS_PTZ),--supports-ptz,) \
		$(if $(FD_SERVICE_URL),--fd-service-url $(FD_SERVICE_URL),) \
		$(if $(METADATA),--metadata $(METADATA),) \
		$(if $(INSECURE),--insecure,) \
		$(if $(VERBOSE),--verbose,) \
		$(if $(NO_HEARTBEAT),--no-heartbeat,)

test:
	cd film-director && uv run --extra test pytest -v
