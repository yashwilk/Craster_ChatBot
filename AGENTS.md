# Coding conventions for this repo (for humans and AI coding agents)

- Python 3.13, type hints throughout, docstrings on every public function.
- New tools go in `app/core/langgraph/tools/`, registered in that package's
  `__init__.py`'s `tools` list. Nothing else needs to change for the agent
  to pick them up.
- New Acumatica-backed tools should go through `app/services/acumatica.py`
  (`acumatica_client.query_gi(...)`) rather than making raw HTTP calls —
  auth, session caching, and retries are centralized there.
- Never log credentials or full Acumatica session cookies.
- Run `make lint && make format` (ruff) and `uv run pyright` before
  committing; CI enforces both plus a detect-secrets scan.
- Config only ever comes from `app/core/config.py` / environment variables —
  no hardcoded hosts, keys, or GI names in tool code.
