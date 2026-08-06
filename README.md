# Craster ChatBot

Craster product & sales assistant — a FastAPI + LangGraph agent that answers questions about Craster's catalog and sales data by calling Acumatica ERP Generic Inquiries (GIs), with long-term per-user memory, streaming responses, and full observability (Langfuse traces, Prometheus/Grafana metrics).

> For a line-by-line trace of every request from HTTP entry to response — including exactly how JWTs are minted and verified — see [`dataflow.md`](dataflow.md). For narrower topic write-ups see [`docs/`](docs/) and repo conventions in [`AGENTS.md`](AGENTS.md).

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running with Docker](#running-with-docker)
- [Database & migrations](#database--migrations)
- [API reference](#api-reference)
- [Authentication](#authentication)
- [The agent: LangGraph + tools](#the-agent-langgraph--tools)
- [Acumatica integration](#acumatica-integration)
- [Observability](#observability)
- [Evaluation framework](#evaluation-framework)
- [Development workflow](#development-workflow)
- [Known gaps](#known-gaps)

## Overview

Users authenticate, open a chat session, and ask questions in natural language ("what banquet risers do we have under $500?", "show me sales of the Elevate line last quarter"). The agent:

1. Loads relevant long-term memory for the user (mem0 + pgvector).
2. Calls an LLM (OpenAI, via a registry with automatic retry/fallback across models).
3. If the model decides it needs data, it calls a tool — `search_products` / `search_sales` (both query Acumatica GIs), `duckduckgo_search` (general web search), or `ask_human` (pause and ask the user for clarification).
4. Loops model ↔ tools until the model produces a final answer, then persists the turn to both chat history (Postgres, via LangGraph's checkpointer) and long-term memory.

Responses can be returned in full (`/chat`) or streamed token-by-token over SSE (`/chat/stream`).

## Architecture

```
Client
  │  Bearer JWT
  ▼
FastAPI app (app/main.py)
  │  CORS → CorrelationId → RateLimit → Metrics → LoggingContext → (DEBUG: Profiling)
  ▼
API routers (app/api/v1)
  ├─ /auth      → register / login / session issue+manage
  └─ /chatbot   → chat / chat/stream / messages
       │
       ▼
LangGraphAgent (app/core/langgraph/graph.py)
  │  chat ⇄ tool_call loop, checkpointed to Postgres
  ▼
LLMService (app/services/llm) ──fallback chain──▶ gpt-5-mini → gpt-5 → gpt-5-nano
  │
  ▼
Tools: search_products / search_sales ──▶ AcumaticaClient ──▶ Acumatica OData GIs
       duckduckgo_search / ask_human

Cross-cutting: MemoryService (mem0 + pgvector), CacheService (Valkey/Redis or in-process),
Langfuse tracing, Prometheus metrics, structlog logging.
```

See [`docs/architecture.md`](docs/architecture.md) for the narrative version and [`dataflow.md`](dataflow.md) for the exhaustive function-by-function trace.

## Tech stack

Every entry below is an actual dependency in [`pyproject.toml`](pyproject.toml) or a concrete piece of infrastructure in this repo — not an aspirational list.

### Language & tooling

| Technology | Version | Purpose |
|---|---|---|
| Python | ≥3.13 (`.python-version`) | Language runtime |
| [uv](https://github.com/astral-sh/uv) | — | Dependency resolution/locking (`uv.lock`) and virtualenv management; replaces pip/poetry |
| [ruff](https://github.com/astral-sh/ruff) | ≥0.11.4 | Linting (`E`, `F`, `B` rule sets) and formatting, line-length 119 |
| [pyright](https://github.com/microsoft/pyright) | ≥1.1.390 | Static type checking (`standard` mode) over `app/` and `evals/` |
| [pre-commit](https://pre-commit.com/) | ≥4.5.1 | Runs ruff/ruff-format/detect-secrets on every commit |
| [detect-secrets](https://github.com/Yelp/detect-secrets) | ≥1.5.0 | Scans staged files and CI for accidentally-committed credentials (`.secrets.baseline`) |
| [pytest](https://pytest.org) | ≥8.3.5 (dependency-group `test`) | Test runner |
| [pyinstrument](https://github.com/joerick/pyinstrument) | ≥5.1.2 (dev extra) | Powers `ProfilingMiddleware`'s per-request flamegraphs in `DEBUG` mode |

### Web framework & server

| Technology | Version | Purpose |
|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | ≥0.121.0 | HTTP API framework — routing, validation, OpenAPI docs at `/docs` |
| [Starlette](https://www.starlette.io/) | (FastAPI dep) | ASGI toolkit FastAPI is built on; `BaseHTTPMiddleware` powers `MetricsMiddleware`/`LoggingContextMiddleware`/`ProfilingMiddleware` |
| [Uvicorn](https://www.uvicorn.org/) | ≥0.34.0 | ASGI server that runs the app (`make dev`/`make prod`) |
| [asgi-correlation-id](https://github.com/snok/asgi-correlation-id) | ≥4.3.4 | Generates/propagates an `X-Request-ID` per request, threaded into logs |
| [asgiref](https://github.com/django/asgiref) | ≥3.8.1 | ASGI spec utilities/sync-to-async bridging |
| [slowapi](https://github.com/laurentS/slowapi) | ≥0.1.9 | Per-endpoint rate limiting (`app/core/limiter.py`), Valkey-backed when configured so limits hold across replicas |
| [python-multipart](https://github.com/Kludex/python-multipart) | ≥0.0.20 | Parses the form-encoded `/auth/login` request body |

### Agent orchestration & LLM

| Technology | Version | Purpose |
|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | ≥1.0.2 | The `chat ⇄ tool_call` `StateGraph` that drives every conversation turn (`app/core/langgraph/graph.py`) |
| `langgraph-checkpoint-postgres` | ≥3.0.1 | `AsyncPostgresSaver` — persists graph state per session (`thread_id`) to Postgres |
| [LangChain](https://github.com/langchain-ai/langchain) (`langchain`, `langchain-core`) | ≥1.0.5 / ≥1.0.4 | Message types (`AIMessage`, `ToolMessage`, …), tool decorator, message-trimming utilities |
| `langchain-openai` | ≥1.0.2 | `ChatOpenAI` wrapper used by `LLMRegistry` |
| `langchain-community` | ≥0.4.1 | Supplies `DuckDuckGoSearchResults` for the web-search tool |
| [OpenAI](https://platform.openai.com/) | via `langchain-openai` | LLM provider — models `gpt-5-mini`, `gpt-5`, `gpt-5-nano` registered in `app/services/llm/registry.py`, called with automatic retry (`tenacity`) and circular fallback across all three |
| [tiktoken](https://github.com/openai/tiktoken) | ≥0.8.0 | Local token counting for trimming chat history to `MAX_TOKENS` without an API round-trip |
| [tenacity](https://github.com/jd/tenacity) | ≥9.1.2 | Exponential-backoff retry decorator used by the LLM service and the Acumatica client |
| [mem0](https://github.com/mem0ai/mem0) (`mem0ai`) | ≥1.0.0 | Long-term, per-user semantic memory — extracts/recalls facts across sessions |
| [ddgs](https://github.com/deedy5/ddgs) | ≥9.6.0 | DuckDuckGo search backend for the `duckduckgo_search` tool |

### Data & persistence

| Technology | Version | Purpose |
|---|---|---|
| [PostgreSQL](https://www.postgresql.org/) + [pgvector](https://github.com/pgvector/pgvector) | — | Single database serving three roles: app tables (User/Session), LangGraph checkpoints, and mem0's vector store |
| [SQLModel](https://sqlmodel.tiangolo.com/) | ≥0.0.25 | ORM/schema layer for `User`/`Session` (combines SQLAlchemy + Pydantic) |
| [Alembic](https://alembic.sqlalchemy.org/) | ≥1.18.4 | Schema migrations for app-owned tables (checkpoint/mem0 tables are excluded from autogenerate) |
| [psycopg](https://www.psycopg.org/) (`psycopg[binary]`, `psycopg2-binary`) | ≥3.3.2 / ≥2.9.10 | Postgres drivers — async `psycopg` for the LangGraph connection pool, `psycopg2` for the sync SQLModel engine |
| [Valkey](https://valkey.io/) (Redis-compatible) | via `redis` ≥7.4.0 (optional `cache` extra) | Distributed cache for session-memory lookups, Acumatica session cookies, and the rate-limiter's shared counter; falls back to an in-process TTL cache when unset |

### Auth & validation

| Technology | Version | Purpose |
|---|---|---|
| [python-jose](https://github.com/mpdavis/python-jose) (`[cryptography]`) | ≥3.4.0 | Signs/verifies the HS256 JWTs used for both user and session tokens (`app/utils/auth.py`) |
| [bcrypt](https://github.com/pyca/bcrypt) | ≥4.3.0 | Password hashing (`User.hash_password`/`verify_password`) |
| [passlib](https://passlib.readthedocs.io/) (`[bcrypt]`) | ≥1.7.4 | Password-hashing scheme management alongside bcrypt |
| [Pydantic](https://docs.pydantic.dev/) (`[email]`) / `pydantic-settings` | ≥2.11.1 / ≥2.8.1 | Request/response schema validation (`app/schemas/`) and settings scaffolding |
| `email-validator` | ≥2.2.0 | Backs Pydantic's `EmailStr` validation on registration |
| `python-dotenv` | ≥1.1.0 | Loads `.env.*` files into the process environment |

### Observability & monitoring

| Technology | Version | Purpose |
|---|---|---|
| [Langfuse](https://langfuse.com/) | ==3.9.1 | Traces every LLM call (prompts, tool calls, latency) for debugging and for the [evaluation framework](#evaluation-framework) to grade |
| [Prometheus](https://prometheus.io/) | via `prometheus-client` ≥0.19.0, `starlette-prometheus` ≥0.7.0 | Scrapes `/metrics` — HTTP, LLM inference/stream, and Acumatica tool-call metrics |
| [Grafana](https://grafana.com/) | — | Dashboards over the Prometheus data (`grafana/dashboards/`), provisioned automatically on container start |
| [structlog](https://www.structlog.org/) | ≥25.2.0 | Structured (JSON in staging/prod, console in dev) logging with request-scoped context (`session_id`, `user_id`, `request_id`) |
| [httpx](https://www.python-httpx.org/) | ≥0.28.1 | Async HTTP client used by the Acumatica client for login + OData GI calls |

### Infrastructure & CI/CD

| Technology | Purpose |
|---|---|
| [Docker](https://www.docker.com/) / Docker Compose | Containerizes the app; `docker-compose.yml` orchestrates app + Valkey + Prometheus + Grafana |
| [GitHub Actions](https://github.com/features/actions) | `.github/workflows/ci.yaml` (lint/format/typecheck/secrets-scan on every PR) and `.github/workflows/deploy.yaml` (build + push image to Docker Hub) |



## Project structure

```
app/
  main.py                  FastAPI app, lifespan, middleware wiring, /, /health
  api/v1/
    api.py                 Router mount points
    auth.py                register/login/session endpoints + get_current_user/get_current_session deps
    chatbot.py             chat/chat-stream/messages endpoints
  core/
    config.py              Settings (env-var driven), Environment enum
    langgraph/
      graph.py              LangGraphAgent — the chat/tool_call state graph
      tools/                duckduckgo_search, ask_human, acumatica_product, acumatica_sales
    prompts/                system.md, session_title.md + loader
    cache.py, limiter.py, middleware.py, metrics.py, observability.py, logging.py
  models/                  SQLModel tables: User, Session, base mixins
  schemas/                 Pydantic request/response models (auth, chat)
  services/
    database.py            User/Session CRUD (sync SQLModel engine)
    acumatica.py            AcumaticaClient — login + OData GI queries
    llm/                    LLMService (retry/fallback), LLMRegistry (model instances)
    memory.py               MemoryService — mem0 + pgvector, cached
    session_naming.py       Background auto-naming of new sessions
  utils/                    auth.py (JWT), graph.py (message trimming/normalization), sanitization.py
alembic/                   DB migrations (Postgres schema for User/Session)
evals/                     Langfuse trace evaluation framework (see docs/evaluation.md)
docs/                      Topic write-ups: architecture, auth, config, db, docker, evaluation,
                           getting-started, llm-service, memory, observability
grafana/, prometheus/      Dashboards and scrape config for the monitoring stack
scripts/                   build-docker.sh, docker-entrypoint.sh, set_env.sh
```

## Getting started

Prerequisites: Python 3.13, [uv](https://github.com/astral-sh/uv), a reachable Postgres instance with the `vector` extension available, and an OpenAI API key.

```bash
cp .env.example .env.development   # fill in required values — see Configuration below
make install                       # uv sync + pre-commit install
make migrate                       # apply Alembic migrations
make dev                           # uvicorn --reload on :8000
```

Then open `http://localhost:8000/docs` for interactive OpenAPI docs.

Full walkthrough: [`docs/getting-started.md`](docs/getting-started.md).

## Configuration

All configuration is env-var driven through `app/core/config.py`. `.env.example` is the canonical list of variables; the loader picks the first of `.env.{APP_ENV}.local`, `.env.{APP_ENV}`, `.env.local`, `.env` that exists. `APP_ENV` must be one of `development`, `staging`, `production`, `test`.

| Group | Key variables |
|---|---|
| App | `APP_ENV`, `PROJECT_NAME`, `DEBUG`, `API_V1_STR`, `ALLOWED_ORIGINS` |
| LLM | `OPENAI_API_KEY`, `DEFAULT_LLM_MODEL`, `DEFAULT_LLM_TEMPERATURE`, `MAX_TOKENS`, `MAX_LLM_CALL_RETRIES`, `LLM_TOTAL_TIMEOUT`, `SESSION_NAMING_ENABLED` |
| Long-term memory | `LONG_TERM_MEMORY_MODEL`, `LONG_TERM_MEMORY_EMBEDDER_MODEL`, `LONG_TERM_MEMORY_COLLECTION_NAME` |
| Auth | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_DAYS` |
| Postgres | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_POOL_SIZE`, `POSTGRES_MAX_OVERFLOW`, `POSTGRES_SSLMODE` |
| Cache / rate limit | `VALKEY_HOST`, `VALKEY_PORT`, `VALKEY_DB`, `VALKEY_PASSWORD`, `CACHE_TTL_SECONDS`, `RATE_LIMIT_DEFAULT`, per-endpoint `RATE_LIMIT_*` |
| Langfuse | `LANGFUSE_TRACING_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` |
| Acumatica | `ACUMATICA_BASE_URL`, `ACUMATICA_USERNAME`, `ACUMATICA_PASSWORD`, `ACUMATICA_TENANT`, `ACUMATICA_BRANCH`, `ACUMATICA_PRODUCTS_GI`, `ACUMATICA_SALES_GI`, `ACUMATICA_SESSION_TTL_SECONDS`, `ACUMATICA_RESULT_CACHE_TTL_SECONDS` |
| Evaluation | `EVALUATION_LLM`, `EVALUATION_BASE_URL`, `EVALUATION_API_KEY`, `EVALUATION_SLEEP_TIME` |

Details and defaults: [`docs/configuration.md`](docs/configuration.md).

**Acumatica setup.** `search_products` and `search_sales` read from two Generic Inquiries published as OData feeds in Acumatica: `ACUMATICA_PRODUCTS_GI` (default `ProductsSimple`) and `ACUMATICA_SALES_GI` (default `SalesSimple`). To wire these up against your own Acumatica instance:

1. In Acumatica, build/verify the GIs and publish each as an OData endpoint (Generic Inquiry screen → *Expose to OData* / *Publish for OData*).
2. Confirm the field names the GI actually exposes (Acumatica normalizes GI column names, they won't always match the screen labels).
3. Update the field-name constants at the top of [`app/core/langgraph/tools/acumatica_product.py`](app/core/langgraph/tools/acumatica_product.py) (`ITEM_ID_FIELD`, `DESCRIPTION_FIELD`, `CATEGORY_FIELD`, `PRICE_FIELD`, `AVAILABLE_QTY_FIELD`) and the equivalent block in [`acumatica_sales.py`](app/core/langgraph/tools/acumatica_sales.py) to match.
4. Set `ACUMATICA_BASE_URL`/`ACUMATICA_USERNAME`/`ACUMATICA_PASSWORD` (and `ACUMATICA_TENANT`/`ACUMATICA_BRANCH` if your instance requires them).

> **Security note:** `.gitignore` excludes all `.env.*` files except `.env.example`, so `.env.development` has never been committed to this repo. That said, the local copy currently holds what look like live Postgres credentials — treat it as sensitive, don't paste it into chat/tickets/screenshots, and rotate the credentials if that file has ever left this machine.

## Running with Docker

```bash
make docker-build ENV=development   # docker build via scripts/build-docker.sh
make docker-up                      # brings up db + app only
make docker-logs
make docker-down
```

For the full stack including Prometheus (`:9090`) and Grafana (`:3000`, default `admin`/`admin`):

```bash
make stack-up
make stack-down
```

`docker-entrypoint.sh` fails fast if `JWT_SECRET_KEY` or `OPENAI_API_KEY` is missing at container start, and deliberately does **not** run migrations automatically (unsafe with multiple replicas) — run `make docker-migrate` explicitly after deploying. See [`docs/docker.md`](docs/docker.md).

## Database & migrations

Schema is managed with SQLModel + Alembic. LangGraph's own checkpoint tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) and mem0's pgvector tables are owned by their respective libraries and excluded from Alembic autogenerate.

```bash
make migrate                     # alembic upgrade head
make migration MSG="add x"       # alembic revision --autogenerate -m "add x"
make migrate-downgrade
make migrate-history
```

Details: [`docs/database.md`](docs/database.md).

## API reference

Base path: `settings.API_V1_STR` (default `/api/v1`).

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | — | Basic API info |
| GET | `/health` | — | Liveness + DB health (503 if degraded) |
| GET | `/api/v1/health` | — | Lightweight v1 liveness |
| POST | `/api/v1/auth/register` | — | Create a user; returns a user access token |
| POST | `/api/v1/auth/login` | — | Exchange email/password (form-encoded) for an access token |
| POST | `/api/v1/auth/session` | user token | Create a new chat session; returns a session token |
| GET | `/api/v1/auth/sessions` | user token | List all sessions for the authenticated user |
| DELETE | `/api/v1/auth/session/{session_id}` | session token | Delete the current session |
| PATCH | `/api/v1/auth/session/{session_id}/name` | session token | Rename the current session |
| POST | `/api/v1/chatbot/chat` | session token | Send a message, get the full reply |
| POST | `/api/v1/chatbot/chat/stream` | session token | Send a message, stream the reply (SSE) |
| GET | `/api/v1/chatbot/messages` | session token | Fetch session message history |
| DELETE | `/api/v1/chatbot/messages` | session token | Clear session message history |

All chat/session endpoints are rate-limited per-endpoint (see `RATE_LIMIT_*` settings). Full interactive schema at `/docs` once the app is running.

## Authentication

Two independent JWT types share one encode/verify path (`app/utils/auth.py`):

- **User token** — `sub` = user id. Minted on `/register` and `/login`. Required to create/list sessions.
- **Session token** — `sub` = chat session id (a UUID). Minted on `/auth/session` (and re-minted on rename/list). Required for every chat/message endpoint.

Tokens are HS256 JWTs signed with `JWT_SECRET_KEY`, expiring after `JWT_ACCESS_TOKEN_EXPIRE_DAYS`. Passwords are hashed with bcrypt (`User.hash_password` / `User.verify_password`), never stored or logged in plaintext. See [`docs/authentication.md`](docs/authentication.md) for the model, and [`dataflow.md`](dataflow.md#authentication--token-lifecycle) for the exact call chain from HTTP request to `jwt.encode`/`jwt.decode`.

## The agent: LangGraph + tools

`LangGraphAgent` (`app/core/langgraph/graph.py`) compiles a two-node `StateGraph`:

- **`chat`** — loads the system prompt + trimmed history, calls the LLM. If the model emits tool calls, routes to `tool_call`; otherwise ends the turn.
- **`tool_call`** — executes the requested tool(s) (in parallel if there are multiple), feeds results back, routes back to `chat`.

State is checkpointed to Postgres per session (`thread_id`) via `AsyncPostgresSaver`, so conversations survive restarts and support the `ask_human` interrupt/resume flow. Available tools (`app/core/langgraph/tools/__init__.py`): `duckduckgo_search_tool`, `ask_human`, `search_products`, `search_sales`.

## Acumatica integration

All Acumatica access goes through a single client, `AcumaticaClient` (`app/services/acumatica.py`):

- Logs in against `/entity/auth/login`, caches the resulting session cookie (Valkey if configured, else in-process) for `ACUMATICA_SESSION_TTL_SECONDS`.
- Queries a GI's OData feed (`/odata/{gi_name}`) with `$filter`/`$select`/`$top`; on a `401` it refreshes the session once and retries; the whole call is wrapped in a 2-attempt tenacity retry.
- `search_products` and `search_sales` (`app/core/langgraph/tools/acumatica_product.py` / `acumatica_sales.py`) build OData filters and call `query_gi`, emitting `acumatica_tool_calls_total` / `acumatica_tool_duration_seconds` Prometheus metrics either way.

New Acumatica-backed tools must reuse `acumatica_client.query_gi(...)` rather than calling Acumatica's REST API directly — see [`AGENTS.md`](AGENTS.md).

## Observability

- **Tracing** — every LLM call is traced to Langfuse when `LANGFUSE_TRACING_ENABLED=true` (`app/core/observability.py`).
- **Metrics** — Prometheus metrics exposed at `/metrics`: HTTP request count/duration, LLM inference/stream duration, Acumatica tool call count/duration, session-naming outcomes. Grafana ships with an LLM-latency dashboard.
- **Logging** — structlog, with `session_id`/`user_id` bound into every log line by `LoggingContextMiddleware` (decoded straight from the request's bearer token) and a correlation ID from `asgi-correlation-id`.
- **Profiling** — in `DEBUG` mode, `ProfilingMiddleware` captures a pyinstrument flamegraph + memory snapshot for any request over `PROFILING_THRESHOLD_SECONDS`, written to `PROFILING_DIR`.

See [`docs/observability.md`](docs/observability.md).

## Evaluation framework

`evals/` pulls unscored Langfuse traces from the last 24 hours and grades each against rubric prompts in `evals/metrics/prompts/` (relevancy, hallucination, helpfulness, conciseness, toxicity — including a check that product/sales claims are grounded in tool output rather than invented). Scores are pushed back to Langfuse and a JSON report is written to `evals/reports/`.

```bash
make eval             # full run
make eval-quick       # --quick
make eval-no-report   # --no-report
```

See [`docs/evaluation.md`](docs/evaluation.md).

## Development workflow

```bash
make lint         # ruff check
make format        # ruff format
make typecheck      # pyright
make check          # lint + typecheck
make pre-commit      # run all pre-commit hooks
```

Before committing: run `make lint && make format` and `uv run pyright`; CI additionally runs a `detect-secrets` scan against every tracked file. Conventions (LangGraph tool registration, Acumatica access rules, config-only-via-env, no credential logging) are documented in [`AGENTS.md`](AGENTS.md) — read it before adding a tool or touching auth/Acumatica code.

## Known gaps

- **No `Dockerfile` at the repo root.** `docker-compose.yml`, `scripts/build-docker.sh`, and `.github/workflows/deploy.yaml` all assume one exists; the deploy workflow's `docker build` step will fail until it's added.
- **No `LICENSE`.** This is an internal Craster tool and not currently intended for open-source release, so a license file was intentionally deferred — add one (proprietary or otherwise) before sharing the repo outside the org. [`SECURITY.md`](SECURITY.md) has been added with a vulnerability-reporting contact.
- **Live-looking Postgres credentials in the local `.env.development`.** Not committed — `.gitignore` excludes every `.env.*` file except `.env.example` — but treat the local copy as sensitive and rotate the credentials if it's ever left this machine. See the security note under [Configuration](#configuration).
