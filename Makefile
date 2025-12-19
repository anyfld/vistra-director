.PHONY: register-camera test lint format-check find-projects type-check test-film-director all-status-check

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
		$(if $(PTZ_SWAP_PAN_TILT),--ptz-swap-pan-tilt,) \
		$(if $(PTZ_INVERT_PAN),--ptz-invert-pan,) \
		$(if $(PTZ_INVERT_TILT),--ptz-invert-tilt,) \
		$(if $(METADATA),--metadata $(METADATA),) \
		$(if $(INSECURE),--insecure,) \
		$(if $(VERBOSE),--verbose,) \
		--webrtc-connection-name "$(if $(WEBRTC_CONNECTION_NAME),$(WEBRTC_CONNECTION_NAME),camera)"

test:
	cd film-director && uv run --extra test pytest -v

lint:
	uvx ruff check .

format-check:
	uvx ruff format --check --diff .

find-projects:
	@find . -type f -name pyproject.toml -exec dirname {} \;

type-check:
	@for project in $$(find . -mindepth 1 -type f -name pyproject.toml -exec dirname {} \;); do \
		echo "Running type check in $$project"; \
		(cd "$$project" && uv sync --dev && uvx --python $$(uv run which python) ty check) || exit 1; \
	done

test-film-director:
	cd film-director && uv sync --dev --extra test && uv run --extra test pytest

all-status-check: lint format-check type-check test-film-director
	@echo "All status checks passed"
