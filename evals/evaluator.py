"""Evaluator: scores unscored Langfuse traces against every metric prompt."""

import os
import sys
import time
from datetime import datetime, timedelta
from time import sleep

import openai
from langfuse import Langfuse
from langfuse.api.resources.commons.types.trace_with_details import TraceWithDetails
from tqdm import tqdm

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.logging import logger
from evals.helpers import (
    calculate_avg_scores,
    generate_report,
    get_input_output,
    initialize_metrics_summary,
    initialize_report,
    process_trace_results,
    update_failure_metrics,
    update_success_metrics,
)
from evals.metrics import metrics
from evals.schemas import ScoreSchema


class Evaluator:
    """Fetches unscored Langfuse traces, grades them with an LLM, pushes scores back."""

    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=settings.EVALUATION_API_KEY, base_url=settings.EVALUATION_BASE_URL)
        self.langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, timeout=60
        )
        self.report = initialize_report(settings.EVALUATION_LLM)
        initialize_metrics_summary(self.report, metrics)

    async def run(self, generate_report_file: bool = True):
        """Fetch, evaluate, and score every unscored trace from the last 24h."""
        start_time = time.time()
        traces = self.__fetch_traces()
        self.report["total_traces"] = len(traces)
        trace_results = {}

        for trace in tqdm(traces, desc="Evaluating traces"):
            trace_id = trace.id
            trace_results[trace_id] = {
                "success": False,
                "metrics_evaluated": 0,
                "metrics_succeeded": 0,
                "metrics_results": {},
            }

            for metric in tqdm(metrics, desc=f"Applying metrics to {trace_id[:8]}...", leave=False):
                metric_name = metric["name"]
                input_text, output_text = get_input_output(trace)
                if input_text is None or output_text is None:
                    update_failure_metrics(self.report, trace_id, metric_name, trace_results)
                    trace_results[trace_id]["metrics_evaluated"] += 1
                    continue

                score = await self._run_metric_evaluation(metric, input_text, output_text)
                if score:
                    self._push_to_langfuse(trace, score, metric)
                    update_success_metrics(self.report, trace_id, metric_name, score, trace_results)
                else:
                    update_failure_metrics(self.report, trace_id, metric_name, trace_results)
                trace_results[trace_id]["metrics_evaluated"] += 1

            process_trace_results(self.report, trace_id, trace_results, len(metrics))
            sleep(settings.EVALUATION_SLEEP_TIME)

        self.report["duration_seconds"] = round(time.time() - start_time, 2)
        calculate_avg_scores(self.report)
        if generate_report_file:
            generate_report(self.report)

        logger.info(
            "evaluation_completed",
            total_traces=self.report["total_traces"],
            successful_traces=self.report["successful_traces"],
            failed_traces=self.report["failed_traces"],
        )

    def _push_to_langfuse(self, trace: TraceWithDetails, score: ScoreSchema, metric: dict):
        self.langfuse.create_score(
            trace_id=trace.id, name=metric["name"], data_type="NUMERIC", value=score.score, comment=score.reasoning
        )

    async def _run_metric_evaluation(self, metric: dict, input_text: str, output_text: str) -> ScoreSchema | None:
        if not input_text or not output_text:
            return None
        return await self._call_openai(metric["prompt"], input_text, output_text)

    async def _call_openai(self, metric_system_prompt: str, input_text: str, output_text: str) -> ScoreSchema | None:
        for _ in range(3):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=settings.EVALUATION_LLM,
                    messages=[
                        {"role": "system", "content": metric_system_prompt},
                        {"role": "user", "content": f"Input: {input_text}\nGeneration: {output_text}"},
                    ],
                    response_format=ScoreSchema,
                )
                return response.choices[0].message.parsed
            except Exception as e:
                logger.error("openai_evaluation_call_failed", error=str(e))
                sleep(10)
        return None

    def __fetch_traces(self) -> list[TraceWithDetails]:
        last_24_hours = datetime.now() - timedelta(hours=24)
        try:
            traces = self.langfuse.api.trace.list(
                from_timestamp=last_24_hours, order_by="timestamp.asc", limit=100
            ).data
            return [t for t in traces if not t.scores]
        except Exception as e:
            logger.error("langfuse_traces_fetch_failed", error=str(e))
            return []
