# LLM Service

`app/services/llm/service.py` wraps every model in `LLMRegistry`
(`app/services/llm/registry.py`) with:
1. Per-call exponential-backoff retry (tenacity) on rate limits/timeouts.
2. Circular fallback — on exhaustion, rotates to the next registered model.
3. A total timeout budget (`LLM_TOTAL_TIMEOUT`) wrapping both.
