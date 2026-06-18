"""Run or compare local reasoning benchmarks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.reasoning.comparison import (
    failed_model_row,
    summarize_benchmark_report,
    write_comparison_summary,
)
from benchmarks.reasoning.suite import (
    EVALUATION_MODES,
    load_prompt_suite,
    run_reasoning_benchmark,
    write_benchmark_report,
)
from voice_concierge.reasoning import (
    DEFAULT_MODEL_SELECTION_PATH,
    DeterministicReasoningFake,
    OllamaConfig,
    OllamaReasoningEngine,
    OllamaReasoningError,
    ReasoningEngine,
    load_model_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / DEFAULT_MODEL_SELECTION_PATH


def parse_args() -> argparse.Namespace:
    """Parse the selected benchmark subcommand and its options."""

    parser = argparse.ArgumentParser(
        description="Run or compare local reasoning benchmarks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the suite against one reasoning engine.",
    )
    _add_common_args(
        run_parser,
        timeout_s=120.0,
        evaluation_mode="guarded",
    )
    run_parser.add_argument(
        "--engine",
        choices=("fake", "ollama"),
        default="fake",
        help="Reasoning engine to benchmark.",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help=(
            "Local model name for --engine ollama. Defaults to the persisted "
            "model selection."
        ),
    )
    run_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for writing the detailed benchmark report JSON.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Run the suite against two or more local Ollama models.",
    )
    _add_common_args(
        compare_parser,
        timeout_s=180.0,
        evaluation_mode="both",
    )
    compare_parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="Two or more local Ollama model names to compare.",
    )
    compare_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for per-model reports and comparison summaries.",
    )

    args = parser.parse_args()
    if args.command == "compare" and len(args.models) < 2:
        parser.error("compare requires at least two models")
    return args


def _add_common_args(
    parser: argparse.ArgumentParser,
    *,
    timeout_s: float,
    evaluation_mode: str,
) -> None:
    """Add options shared by single-run and comparison modes."""

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the local model-selection config JSON.",
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "reasoning" / "prompts" / "v0.json",
        help="Path to the reasoning prompt suite JSON.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Ollama host URL. Defaults to the persisted model selection.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=timeout_s,
        help="HTTP timeout in seconds per Ollama request.",
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
        default=evaluation_mode,
        help="Evaluate raw output, guarded output, or both from one generation.",
    )


def build_engine(args: argparse.Namespace) -> ReasoningEngine:
    """Build the engine selected for a single benchmark run."""

    if args.engine == "fake":
        return DeterministicReasoningFake()

    if args.engine == "ollama":
        model, host = _resolve_ollama_run_settings(args)
        return OllamaReasoningEngine(
            OllamaConfig(
                model=model,
                host=host,
                timeout_s=args.timeout_s,
            )
        )

    raise ValueError(f"Unsupported engine: {args.engine}")


def main() -> int:
    """Dispatch the requested benchmark mode."""

    args = parse_args()
    if args.command == "run":
        return _run_single(args)
    if args.command == "compare":
        return _compare_models(args)
    raise ValueError(f"Unsupported command: {args.command}")


def _run_single(args: argparse.Namespace) -> int:
    """Run one engine and print or persist its detailed report."""

    try:
        engine = build_engine(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    suite = load_prompt_suite(args.prompts)
    try:
        report = run_reasoning_benchmark(
            engine,
            suite,
            max_words=args.max_words,
            evaluation_mode=args.evaluation_mode,
        )
    except (OllamaReasoningError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output:
        write_benchmark_report(report, args.output)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _compare_models(args: argparse.Namespace) -> int:
    """Run multiple Ollama models and write detailed and summary reports."""

    try:
        host = _resolve_ollama_host(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    suite = load_prompt_suite(args.prompts)
    output_dir = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for model in args.models:
        report_path = output_dir / f"{_model_slug(model)}.json"
        try:
            engine = OllamaReasoningEngine(
                OllamaConfig(
                    model=model,
                    host=host,
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


def _resolve_ollama_run_settings(
    args: argparse.Namespace,
) -> tuple[str, str]:
    if args.model is not None and args.host is not None:
        return args.model, args.host

    selection = load_model_selection(args.config)
    if args.model is None:
        if selection.backend != "ollama":
            raise ValueError(
                f"Selected model backend {selection.backend!r} is not supported "
                "by the Ollama benchmark engine."
            )
        model = selection.model
    else:
        model = args.model

    host = args.host or selection.host
    return model, host


def _resolve_ollama_host(args: argparse.Namespace) -> str:
    if args.host is not None:
        return args.host
    return load_model_selection(args.config).host


def _default_output_dir() -> Path:
    """Return a timestamped output directory for a model comparison."""

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return (
        REPO_ROOT / "benchmarks" / "reasoning" / "results" / f"model-comparison-{stamp}"
    )


def _model_slug(model: str) -> str:
    """Convert a model name into a safe report filename stem."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
