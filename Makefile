.PHONY: help prerequisites install lint format typecheck test test-unit test-fga test-integration test-e2e check clean run run-auto openfga openfga-stop openfga-setup fga-reset security audit dead-code web-install web-dev web-backend web-frontend web-build auth-linear auth-slack auth-notion

UV     := uv
RUN    := $(UV) run

SRC    := src/agent.py src/mcp_server.py src/mcp_remote.py src/task_authz/ src/utils.py src/test_remote_server.py src/servers/
WEB_SRC := web/backend/
TESTS  := tests/
PY_DIRS := src tests web/backend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

prerequisites: ## Install prerequisite tools (uv, docker, fga, jq, node) via Homebrew
	@echo "Checking prerequisites..."
	@missing=""; \
	command -v brew  >/dev/null 2>&1 || { echo "ERROR: Homebrew is required. Install from https://brew.sh"; exit 1; }; \
	command -v uv     >/dev/null 2>&1 || missing="$$missing uv"; \
	command -v docker >/dev/null 2>&1 || missing="$$missing docker"; \
	command -v fga    >/dev/null 2>&1 || missing="$$missing openfga/tap/fga"; \
	command -v jq     >/dev/null 2>&1 || missing="$$missing jq"; \
	command -v node   >/dev/null 2>&1 || missing="$$missing node"; \
	if [ -z "$$missing" ]; then \
		echo "All prerequisites already installed."; \
	else \
		echo "Installing:$$missing"; \
		brew install $$missing; \
	fi
	@echo ""
	@echo "Versions:"
	@uv --version
	@docker --version
	@fga version 2>/dev/null || echo "fga: installed (version check unsupported)"
	@jq --version
	@node --version

install: ## Install all dependencies (creates venv automatically)
	$(UV) sync

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

lint: ## Lint with ruff
	$(RUN) ruff check $(SRC) $(TESTS) $(WEB_SRC)

format: ## Auto-format with ruff
	$(RUN) ruff format $(SRC) $(TESTS) $(WEB_SRC)
	$(RUN) ruff check --fix $(SRC) $(TESTS) $(WEB_SRC)

typecheck: ## Type-check with mypy (best-effort, no strict)
	MYPYPATH=src $(RUN) mypy --ignore-missing-imports $(SRC) $(WEB_SRC)

security: ## Scan for security vulnerabilities with bandit
	$(RUN) bandit -r $(SRC) $(WEB_SRC) -q

audit: ## Check dependencies for known CVEs
	$(RUN) pip-audit

dead-code: ## Find unused code with vulture
	$(RUN) vulture $(SRC) --min-confidence 80

syntax: ## Verify all files parse without errors
	@for f in $$(find $(PY_DIRS) -name '*.py' -not -path '*/__pycache__/*'); do \
		$(RUN) python -c "import ast; ast.parse(open('$$f').read())" && echo "  ✓ $$f" || exit 1; \
	done

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test: test-unit ## Run all fast tests (alias for test-unit)

test-unit: ## Run unit tests (no external services needed)
	$(RUN) pytest tests/test_agent.py tests/test_utils.py tests/test_resolution.py tests/test_linear.py tests/test_mcp_remote.py tests/test_authz_flow_extras.py tests/test_middleware_unit.py tests/test_meta_tools.py tests/test_slack_parser.py tests/test_config.py tests/test_discovery_phase.py -v

test-integration: ## Run OpenFGA integration tests (loads .env; needs local FGA + model)
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) pytest tests/test_permission_openfga.py -v

test-fga: ## Run OpenFGA model tests (needs fga CLI)
	fga model test --tests authorization/model.fga.yaml

test-e2e: ## Run end-to-end tests (loads .env; needs FGA + live Slack/Linear APIs)
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) pytest tests/test_e2e_openfga.py -v -s

test-all: test-unit test-fga test-integration test-e2e  ## Run unit + FGA model + integration + e2e tests

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

run: ## Run interactive agent (loads .env)
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) python src/agent.py

HASH := \#
DEFAULT_PROMPT = Summarize the MCP Dev Talk project and post it to $(HASH)private-team-channel

run-auto: ## Run autonomous agent (loads .env; optional ARG, e.g. make run-auto ARG="Summarize...")
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) python src/agent.py --auto "$(or $(ARG),$(DEFAULT_PROMPT))"

run-verbose: ## Run interactive agent with verbose output (loads .env)
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) python src/agent.py --verbose

run-debug: ## Run interactive agent with debug output (loads .env)
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) python src/agent.py --debug

# ---------------------------------------------------------------------------
# MCP server authentication
# ---------------------------------------------------------------------------

auth-linear: ## Authenticate with Linear (OAuth → saves token to .mcp_credentials.json)
	$(RUN) python scripts/auth_server.py linear

# ---------------------------------------------------------------------------
# OpenFGA
# ---------------------------------------------------------------------------

openfga: ## Start OpenFGA via Docker Compose (detached)
	docker compose up -d openfga

openfga-stop: ## Stop OpenFGA container
	docker compose down

openfga-setup: openfga ## Start OpenFGA, wait for healthy, then create store + model
	@echo "Waiting for OpenFGA to be healthy..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if curl -sf http://localhost:8080/healthz > /dev/null 2>&1; then \
			echo "OpenFGA is ready."; \
			break; \
		fi; \
		if [ $$i -eq 15 ]; then echo "ERROR: OpenFGA did not start within 15s"; exit 1; fi; \
		sleep 1; \
	done
	@$(MAKE) fga-reset

fga-reset: ## Create FGA store + model, save FGA_STORE_ID to .env
	$(eval FGA_STORE_ID := $(shell fga store create --model authorization/model.fga | jq -r '.store.id'))
	@if [ -z "$(FGA_STORE_ID)" ]; then echo "ERROR: failed to create FGA store"; exit 1; fi
	@echo "Created FGA store: $(FGA_STORE_ID)"
	@if grep -q '^FGA_STORE_ID=' .env 2>/dev/null; then \
		sed -i'' -e 's/^FGA_STORE_ID=.*/FGA_STORE_ID=$(FGA_STORE_ID)/' .env; \
	else \
		echo 'FGA_STORE_ID=$(FGA_STORE_ID)' >> .env; \
	fi
	@echo "Updated .env with FGA_STORE_ID=$(FGA_STORE_ID)"
	@echo "Integration targets load .env automatically."
	@echo "For ad-hoc shell commands, run:"
	@echo "  source .env && export FGA_STORE_ID"

# ---------------------------------------------------------------------------
# Check (CI-friendly: lint + syntax + tests)
# ---------------------------------------------------------------------------

check: syntax lint typecheck security test-unit ## Run all static checks + unit tests

# ---------------------------------------------------------------------------
# Web demo
# ---------------------------------------------------------------------------

web-install: install ## Install web demo dependencies (Python + Node)
	cd web/frontend && npm install

web-dev: ## Run web demo (backend + frontend dev servers)
	@echo "Starting backend on :8000 and frontend on :5173..."
	@set -a; [ ! -f .env ] || . ./.env; set +a; \
		$(RUN) uvicorn web.backend.app:app --reload --port 8000 &
	@cd web/frontend && npm run dev

web-backend: ## Run web backend only
	set -a; [ ! -f .env ] || . ./.env; set +a; $(RUN) uvicorn web.backend.app:app --reload --port 8000

web-frontend: ## Run web frontend only
	cd web/frontend && npm run dev

web-build: ## Build web frontend for production
	cd web/frontend && npm run build

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
