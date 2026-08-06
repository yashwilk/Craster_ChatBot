# Observability

- Langfuse tracing on every LLM call (toggle via `LANGFUSE_TRACING_ENABLED`).
- Prometheus metrics at `/metrics`, including `acumatica_tool_calls_total`
  and `acumatica_tool_duration_seconds` for the two new tools.
- Grafana dashboard provisioned from `grafana/dashboards/json/llm_latency.json`.
- DEBUG-only per-request profiling via pyinstrument (`ProfilingMiddleware`).
