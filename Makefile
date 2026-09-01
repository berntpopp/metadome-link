.PHONY: help install lock upgrade sync \
        format format-check lint lint-ci lint-fix lint-loc lint-readme lint-surface \
        typecheck test test-fast test-unit test-integration test-cov \
        check ci-local precommit clean verify-deploy \
        cache-status cache-clear cache-warm dev mcp-serve \
        docker-build docker-up docker-down docker-logs docker-url info

DOCKER_COMPOSE := $(shell if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)
COMPOSE := $(DOCKER_COMPOSE) -f docker/docker-compose.yml $(shell [ -f docker/.env ] && echo "--env-file docker/.env")
APP_VERSION ?= $(shell sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -1)
VCS_REF ?= $(shell git rev-parse HEAD)
BUILD_DATE ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)

.DEFAULT_GOAL := help

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install project and development dependencies with uv
	uv sync --group dev

sync: install ## Alias for install

lock: ## Resolve and update uv.lock
	uv lock

upgrade: ## Upgrade locked dependencies
	uv lock --upgrade

format: ## Format Python code
	uv run ruff format metadome_link tests server.py mcp_server.py scripts

format-check: ## Check formatting without writing
	uv run ruff format --check metadome_link tests server.py mcp_server.py scripts

lint: ## Lint Python code
	uv run ruff check metadome_link tests server.py mcp_server.py scripts

lint-ci: ## Lint with GitHub-Actions output
	uv run ruff check metadome_link tests server.py mcp_server.py scripts --output-format=github

lint-fix: ## Lint and apply safe fixes
	uv run ruff check metadome_link tests server.py mcp_server.py scripts --fix

lint-loc: ## Enforce per-file line budget
	uv run python scripts/check_file_size.py

lint-readme: ## Enforce the GeneFoundry README Standard v1
	uv run python scripts/check_readme.py

lint-surface: ## Enforce canonical router B1/B2 and schema-doc S1-S3 gates
	uv run pytest tests/test_tool_surface_budget.py -q

typecheck: ## Type check package
	uv run mypy metadome_link server.py mcp_server.py

test: ## Run unit tests quickly
	uv run pytest tests -q -m "not integration"

test-fast: ## Run unit tests in parallel
	uv run pytest tests -q -m "not integration" -n auto

test-unit: ## Run unit tests
	uv run pytest tests -q -m "not integration"

test-integration: ## Run live-endpoint integration tests
	uv run pytest tests -q -m "integration"

test-cov: ## Run tests with coverage
	uv run pytest tests -m "not integration" --cov=metadome_link --cov-report=term-missing --cov-report=html

check: format lint ## Format and lint

ci-local: format-check lint-ci lint-loc lint-readme lint-surface typecheck test-fast ## Fast local CI-equivalent checks

precommit: ci-local ## Run checks expected before commit

verify-deploy: ## Fail if the deployed build sha != local HEAD (URL=<server>/health)
	@test -n "$(URL)" || { echo "set URL=<server>/health, e.g. http://127.0.0.1:8000/health"; exit 2; }
	curl -fsS "$(URL)" | uv run python scripts/check_deployed_freshness.py

clean: ## Remove local caches and reports
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml dist build

cache-status: ## Print on-disk result cache stats / pinned data version
	uv run metadome-link-cache status

cache-clear: ## Clear the on-disk result cache
	uv run metadome-link-cache clear

cache-warm: ## Warm up to 32 genes for the configured profile (nonzero if any fail)
	uv run metadome-link-cache warm $(GENES)

dev: ## Start unified REST + MCP development server
	uv run python server.py --transport unified --host 127.0.0.1 --port 8000

mcp-serve: ## Start local stdio MCP server
	uv run python mcp_server.py

docker-build: ## Build Docker image
	$(COMPOSE) build --build-arg APP_VERSION=$(APP_VERSION) --build-arg VCS_REF=$(VCS_REF) --build-arg BUILD_DATE=$(BUILD_DATE)

docker-up: ## Start Docker stack (random free host port; see docker/.env)
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory docker-url

docker-down: ## Stop Docker stack
	$(COMPOSE) down

docker-logs: ## Follow Docker logs
	$(COMPOSE) logs -f

docker-url: ## Print the MCP URL (host port the container is published on)
	@hostport=$$($(COMPOSE) port metadome-link 8000 2>/dev/null); \
	port=$${hostport##*:}; \
	if [ -n "$$port" ]; then \
	  echo "metadome-link MCP: http://127.0.0.1:$$port/mcp  (health: http://127.0.0.1:$$port/health)"; \
	  echo "Claude Code: claude mcp add --transport http metadome-link --scope user http://127.0.0.1:$$port/mcp"; \
	else \
	  echo "metadome-link container is not running. Start it with: make docker-up"; \
	fi

info: ## Show project information
	@echo "Project: metadome-link"
	@echo "uv: $(shell uv --version 2>/dev/null || echo 'not installed')"
