# Architecture

Request flow: `main.py` → middleware stack (correlation-id, metrics, logging
context, DEBUG-only profiling) → `api/v1` routes → `LangGraphAgent`
(`core/langgraph/graph.py`) → LLM service (retry + circular fallback) and
tools (`search_products`, `search_sales`, `duckduckgo_search`, `ask_human`).

State persists in Postgres via LangGraph's `AsyncPostgresSaver` checkpointer
(tables: `checkpoints`, `checkpoint_writes`, `checkpoint_blobs`). Long-term,
per-user memory persists separately via mem0 + pgvector.

Acumatica integration: `services/acumatica.py` is the single client every
Acumatica-backed tool goes through — it owns login, session-cookie caching,
and GI querying, so auth and retry logic live in exactly one place.
