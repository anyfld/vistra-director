.PHONY: register-camera test

register-camera:
	@if [ -z "$(NAME)" ] || [ -z "$(MASTER_MF_ID)" ]; then \
		echo "エラー: NAME, MASTER_MF_ID は必須です（ADDRESSは省略時にローカルIP）"; \
		echo "使用例: make register-camera NAME=\"カメラ1\" MASTER_MF_ID=\"mf-001\""; \
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
		$(if $(NO_PTZ),--no-ptz,--supports-ptz) \
		$(if $(VIRTUAL_PTZ),--virtual-ptz,) \
		$(if $(VIRTUAL_PTZ_GUI_PORT),--virtual-ptz-gui-port $(VIRTUAL_PTZ_GUI_PORT),) \
		$(if $(PTZ_SERVICE_URL),--ptz-service-url $(PTZ_SERVICE_URL),) \
		$(if $(METADATA),--metadata $(METADATA),) \
		$(if $(INSECURE),--insecure,) \
		$(if $(VERBOSE),--verbose,)

test:
	cd film-director && uv run --extra test pytest -v
