"""Prometheus metrics."""

from prometheus_client import Counter, Histogram
from starlette_prometheus import metrics, PrometheusMiddleware

http_requests_total = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration (s)", ["method", "endpoint"]
)
llm_inference_duration_seconds = Histogram(
    "llm_inference_duration_seconds",
    "LLM inference time (s)",
    ["model"],
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0],
)
llm_stream_duration_seconds = Histogram(
    "llm_stream_duration_seconds",
    "LLM streaming time (s)",
    ["model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)
session_names_generated_total = Counter("session_names_generated_total", "Session names generated", ["status"])

# Acumatica tool metrics
acumatica_tool_calls_total = Counter("acumatica_tool_calls_total", "Total Acumatica GI tool calls", ["tool", "status"])
acumatica_tool_duration_seconds = Histogram(
    "acumatica_tool_duration_seconds",
    "Acumatica GI call duration (s)",
    ["tool"],
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0],
)


def setup_metrics(app):
    """Attach Prometheus middleware and /metrics endpoint."""
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics)
