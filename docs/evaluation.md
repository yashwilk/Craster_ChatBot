# Evaluation

`evals/main.py` pulls unscored Langfuse traces from the last 24h and grades
each against the metrics in `evals/metrics/prompts/*.md` (relevancy,
hallucination, helpfulness, conciseness, toxicity — adapted here to check
that product/sales claims are tool-grounded, not invented). Scores are
pushed back to Langfuse and a JSON report is written to `evals/reports/`.

Run: `uv run python evals/main.py`
