"""Helper functions for the evaluation process."""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langfuse.api.resources.commons.types.trace_with_details import TraceWithDetails

from app.core.logging import logger
from evals.schemas import ScoreSchema


def format_messages(messages: list[dict]) -> str:
    """Render a list of LangChain-style message dicts as readable text."""
    formatted = []
    for idx, message in enumerate(messages):
        if message["type"] == "tool":
            previous = messages[idx - 1]
            tool_call = previous.get("additional_kwargs", {}).get("tool_calls", [])
            args = (
                tool_call[0].get("function", {}).get("arguments")
                if tool_call
                else ((previous.get("tool_calls") or [{}])[0].get("args", {}))
            )
            content = message.get("content") or ""
            formatted.append(
                f"tool {message.get('name')} input: {args} {content[:100]}..."
                if len(content) > 100
                else f"tool {message.get('name')}: {content}"
            )
        elif message["content"]:
            formatted.append(f"{message['type']}: {message['content']}")
    return "\n".join(formatted)


def get_input_output(trace: TraceWithDetails) -> Tuple[Optional[str], Optional[str]]:
    """Split a trace's message list into (formatted_input, formatted_output)."""
    if not isinstance(trace.output, dict):
        return None, None
    input_messages = trace.output.get("messages", [])[:-1]
    output_message = trace.output.get("messages", [])[-1]
    return format_messages(input_messages), format_messages([output_message])


def initialize_report(model_name: str) -> Dict[str, Any]:
    """Build the initial (empty) report structure."""
    return {
        "timestamp": datetime.now().isoformat(),
        "model": model_name,
        "total_traces": 0,
        "successful_traces": 0,
        "failed_traces": 0,
        "duration_seconds": 0,
        "metrics_summary": {},
        "successful_traces_details": [],
        "failed_traces_details": [],
    }


def initialize_metrics_summary(report: Dict[str, Any], metrics: List[Dict[str, str]]) -> None:
    """Seed the metrics_summary section for every metric."""
    for metric in metrics:
        report["metrics_summary"][metric["name"]] = {"success_count": 0, "failure_count": 0, "avg_score": 0.0}


def update_success_metrics(report, trace_id, metric_name, score: ScoreSchema, trace_results) -> None:
    """Record a successful metric evaluation."""
    trace_results[trace_id]["metrics_succeeded"] += 1
    trace_results[trace_id]["metrics_results"][metric_name] = {
        "success": True,
        "score": score.score,
        "reasoning": score.reasoning,
    }
    report["metrics_summary"][metric_name]["success_count"] += 1
    report["metrics_summary"][metric_name]["avg_score"] += score.score


def update_failure_metrics(report, trace_id, metric_name, trace_results) -> None:
    """Record a failed metric evaluation."""
    trace_results[trace_id]["metrics_results"][metric_name] = {"success": False}
    report["metrics_summary"][metric_name]["failure_count"] += 1


def process_trace_results(report, trace_id, trace_results, metrics_count) -> None:
    """Roll a trace's per-metric results into the top-level report."""
    if trace_results[trace_id]["metrics_succeeded"] == metrics_count:
        trace_results[trace_id]["success"] = True
        report["successful_traces"] += 1
        report["successful_traces_details"].append(
            {"trace_id": trace_id, "metrics_results": trace_results[trace_id]["metrics_results"]}
        )
    else:
        report["failed_traces"] += 1
        report["failed_traces_details"].append(
            {
                "trace_id": trace_id,
                "metrics_evaluated": trace_results[trace_id]["metrics_evaluated"],
                "metrics_succeeded": trace_results[trace_id]["metrics_succeeded"],
                "metrics_results": trace_results[trace_id]["metrics_results"],
            }
        )


def calculate_avg_scores(report: Dict[str, Any]) -> None:
    """Average each metric's accumulated score by its success count."""
    for _, data in report["metrics_summary"].items():
        if data["success_count"] > 0:
            data["avg_score"] = round(data["avg_score"] / data["success_count"], 2)


def generate_report(report: Dict[str, Any]) -> str:
    """Write the report to evals/reports/ as timestamped JSON."""
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"evaluation_report_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    report["generate_report_path"] = report_path
    logger.info("evaluation_report_generated", report_path=report_path)
    return report_path
