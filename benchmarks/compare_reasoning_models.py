"""Run the reasoning benchmark across multiple local Ollama models."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from voice_concierge.reasoning import (  # noqa: E402
    DEFAULT_REASONING_MODEL,
    OllamaConfig,
    OllamaReasoningEngine,
)
from voice_concierge.reasoning.benchmark import (  # noqa: E402
    EVALUATION_MODES,
    load_prompt_suite,
    run_reasoning_benchmark,
    write_benchmark_report,
)
from voice_concierge.reasoning.comparison import (  # noqa: E402
    failed_model_row,
    summarize_benchmark_report,
    write_comparison_summary,
)
from voice_concierge.reasoning.ollama import OllamaReasoningError  # noqa: E402

DEFAULT_MODELS = (DEFAULT_REASONING_MODEL,)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare multiple local Ollama models on the reasoning suite.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help=(
            "One or more local Ollama model names. If omitted, defaults to "
            f"{', '.join(DEFAULT_MODELS)}."
        ),
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "reasoning_prompts_v0.json",
        help="Path to the reasoning prompt suite JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for per-model reports and comparison summaries.",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:11434",
        help="Ollama host URL.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=180.0,
        help="HTTP timeout in seconds per model request.",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=60,
        help="Maximum words allowed in a spoken response.",
    )
    parser.add_argument(
        "--evaluation-mode",
        choices=EVALUATION_MODES,
        default="both",
        help=(
            "Evaluate raw model output, guarded product output, or both from "
            "the same generation. Defaults to both."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    suite = load_prompt_suite(args.prompts)
    output_dir = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    models = args.models or list(DEFAULT_MODELS)

    rows = []
    for model in models:
        report_path = output_dir / f"{_model_slug(model)}.json"
        try:
            engine = OllamaReasoningEngine(
                OllamaConfig(
                    model=model,
                    host=args.host,
                    timeout_s=args.timeout_s,
                )
            )
            report = run_reasoning_benchmark(
                engine,
                suite,
                max_words=args.max_words,
                evaluation_mode=args.evaluation_mode,
            )
        except OllamaReasoningError as exc:
            rows.append(failed_model_row(model, str(exc)))
            continue

        write_benchmark_report(report, report_path)
        rows.append(
            summarize_benchmark_report(
                report,
                model=model,
                report_path=report_path,
            )
        )

    summary = write_comparison_summary(rows, output_dir=output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if any(row.error is None for row in rows) else 1


def _default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "benchmarks" / "results" / f"model-comparison-{stamp}"


def _model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
