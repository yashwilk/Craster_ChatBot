.DEFAULT_GOAL := help

DOCKER_COMPOSE ?= docker compose
ENV            ?= development
VALID_ENVS     := development staging production test

define check_env
	@if ! echo "$(VALID_ENVS)" | grep -qw "$(ENV)"; then \
		echo "Invalid ENV=$(ENV). Must be one of: $(VALID_ENVS)"; exit 1; \
	fi
endef

define load_env_file
	$(call check_env)
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Copy .env.example first."; exit 1; \
	fi
endef

run_with_env = bash -c "source scripts/set_env.sh $(ENV) && $(1)"

# --- Setup -------------------------------------------------------------
install:
	pip install uv
	uv sync
	uv run pre-commit install

# --- Server --------------------------------------------------------------
dev:
	@$(call run_with_env,uv run uvicorn app.main:app --reload --port 8000)

staging:
	@$(call run_with_env,$(MAKE) _serve ENV=staging)

prod:
	@$(call run_with_env,$(MAKE) _serve ENV=production)

_serve:
	@$(call run_with_env,./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop)

# --- Database migrations --------------------------------------------------
migrate:
	@$(call run_with_env,uv run alembic upgrade head)

migration:
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migration MSG=\"describe your change\""; exit 1; \
	fi
	@$(call run_with_env,uv run alembic revision --autogenerate -m '$(MSG)')

migrate-downgrade:
	@$(call run_with_env,uv run alembic downgrade -1)

migrate-history:
	@$(call run_with_env,uv run alembic history --verbose)

# --- Evaluation ------------------------------------------------------------
eval:
	@$(call run_with_env,python -m evals.main)

eval-quick:
	@$(call run_with_env,python -m evals.main --quick)

eval-no-report:
	@$(call run_with_env,python -m evals.main --no-report)

# --- Code quality ----------------------------------------------------------
lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck
	@echo "All checks passed"

pre-commit:
	uv run pre-commit run --all-files

pre-commit-update:
	uv run pre-commit autoupdate

# --- Docker: API + DB only ------------------------------------------------
docker-build:
	$(call check_env)
	@./scripts/build-docker.sh $(ENV)

docker-up:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) up -d --build db app

docker-down:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) down

docker-logs:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) logs -f app db

# Migrations run explicitly against the running container — never automatically
# on container start (see scripts/docker-entrypoint.sh for why).
docker-migrate:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) exec -T app /app/.venv/bin/alembic upgrade head

docker-migrate-downgrade:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) exec -T app /app/.venv/bin/alembic downgrade -1

docker-migrate-history:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) exec -T app /app/.venv/bin/alembic history --verbose

# --- Docker: full stack (API + DB + Prometheus + Grafana) ------------------
stack-up:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) up -d --build

stack-down:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) down

stack-logs:
	$(call load_env_file)
	@APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file .env.$(ENV) logs -f

# --- Misc --------------------------------------------------------------
clean:
	rm -rf .venv __pycache__ .pytest_cache

help:
	@echo "Usage: make <target> [ENV=development|staging|production|test]"
	@echo ""
	@echo "Setup:            install"
	@echo "Server:           dev | staging | prod"
	@echo "Database:         migrate | migration MSG=... | migrate-downgrade | migrate-history"
	@echo "Evaluation:       eval | eval-no-report"
	@echo "Code quality:     lint | format | typecheck | check | pre-commit | pre-commit-update"
	@echo "Docker (API+DB):  docker-build | docker-up | docker-down | docker-logs | docker-migrate*"
	@echo "Docker (stack):   stack-up | stack-down | stack-logs   (adds Prometheus + Grafana)"
	@echo "Misc:             clean"

.PHONY: install dev staging prod _serve \
        migrate migration migrate-downgrade migrate-history \
        eval eval-no-report \
        lint format typecheck check pre-commit pre-commit-update \
        docker-build docker-up docker-down docker-logs docker-migrate \
        docker-migrate-downgrade docker-migrate-history \
        stack-up stack-down stack-logs \
        clean help
