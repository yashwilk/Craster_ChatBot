#!/usr/bin/env python3
"""CLI for running trace evaluations: `uv run python evals/main.py --quick`."""

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.logging import logger
from evals.evaluator import Evaluator


async def run_evaluation(generate_report: bool = True) -> None:
    """Run one evaluation pass and print a summary."""
    print(f"Running evaluations with model={settings.EVALUATION_LLM}")
    try:
        evaluator = Evaluator()
        await evaluator.run(generate_report_file=generate_report)
        report = evaluator.report
        rate = (report["successful_traces"] / report["total_traces"] * 100) if report["total_traces"] else 0
        print(f"Done. {report['total_traces']} traces, {rate:.1f}% fully successful.")
        if report.get("generate_report_path"):
            print(f"Report: {report['generate_report_path']}")
    except Exception as e:
        logger.error("evaluation_failed", error=str(e))
        sys.exit(1)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Run evaluations on model outputs")
    parser.add_argument("--no-report", action="store_true", help="Don't generate a JSON report")
    parser.add_argument("--quick", action="store_true", help="Run immediately with default settings (no prompts)")
    args = parser.parse_args()
    asyncio.run(run_evaluation(generate_report=not args.no_report))


if __name__ == "__main__":
    main()
