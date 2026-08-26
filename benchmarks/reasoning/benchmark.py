"""Run or compare local reasoning benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import psutil

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
    DEFAULT_PROMPT_VERSION,
    DeterministicReasoningFake,
    LocalModelInfo,
    OllamaConfig,
    OllamaModelManagementError,
    OllamaModelManager,
    OllamaModelManagerConfig,
    OllamaReasoningEngine,
    OllamaReasoningError,
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningConstraints,
    ReasoningEngine,
    ReasoningModelUnavailableError,
    ReasoningRequest,
    build_reasoning_engine,
    load_model_selection,
    load_prompt_template,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / DEFAULT_MODEL_SELECTION_PATH
DEFAULT_PROMPT_SUITE_PATH = (
    REPO_ROOT / "benchmarks" / "reasoning" / "prompts" / "final-v1.json"
)


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
        repetitions=1,
        warmup_runs=0,
        num_predict=None,
    )
    run_parser.add_argument(
        "--engine",
        choices=("fake", "ollama", "selected"),
        default="fake",
        help=(
            "Reasoning engine to benchmark. Use 'selected' to exercise the "
            "app-facing configured runtime through build_reasoning_engine()."
        ),
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
        repetitions=3,
        warmup_runs=1,
        num_predict=512,
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
    if args.repetitions <= 0:
        parser.error("--repetitions must be greater than zero")
    if args.warmup_runs < 0:
        parser.error("--warmup-runs must not be negative")
    if args.num_predict is not None and args.num_predict <= 0:
        parser.error("--num-predict must be greater than zero")
    if (
        args.command == "run"
        and args.engine == "selected"
        and (args.model is not None or args.host is not None)
    ):
        parser.error("--engine selected uses --config; do not pass --model or --host")
    return args


def _add_common_args(
    parser: argparse.ArgumentParser,
    *,
    timeout_s: float,
    evaluation_mode: str,
    repetitions: int,
    warmup_runs: int,
    num_predict: int | None,
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
        default=DEFAULT_PROMPT_SUITE_PATH,
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
        "--num-predict",
        type=int,
        default=num_predict,
        help=(
            "Fixed generation-token budget. Omit in single-run mode to derive "
            "the budget from --max-words."
        ),
    )
    parser.add_argument(
        "--prompt-version",
        default=DEFAULT_PROMPT_VERSION,
        help="Bundled runtime prompt-template version used by Ollama engines.",
    )
    parser.add_argument(
        "--evaluation-mode",
        choices=EVALUATION_MODES,
        default=evaluation_mode,
        help="Evaluate raw output, guarded output, or both from one generation.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=repetitions,
        help="Number of times to execute every case for each model.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=warmup_runs,
        help="Unmeasured generation requests to run before the benchmark.",
    )


def build_engine(args: argparse.Namespace) -> ReasoningEngine:
    """Build the engine selected for a single benchmark run."""

    if args.engine == "fake":
        return DeterministicReasoningFake()

    if args.engine == "selected":
        return build_reasoning_engine(
            args.config,
            prompt_version=args.prompt_version,
            timeout_s=args.timeout_s,
        )

    if args.engine == "ollama":
        model, host = _resolve_ollama_run_settings(args)
        return OllamaReasoningEngine(
            OllamaConfig(
                model=model,
                host=host,
                timeout_s=args.timeout_s,
                prompt_version=args.prompt_version,
                num_predict=getattr(args, "num_predict", None),
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
    except ReasoningConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (
        ReasoningBackendUnavailableError,
        ReasoningModelUnavailableError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    suite = load_prompt_suite(args.prompts)
    try:
        warmup = _warm_up_engine(
            engine,
            runs=args.warmup_runs,
            max_words=args.max_words,
        )
        report = run_reasoning_benchmark(
            engine,
            suite,
            max_words=args.max_words,
            evaluation_mode=args.evaluation_mode,
            repetitions=args.repetitions,
        )
    except (OllamaReasoningError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report["experiment"] = _experiment_metadata(args, suite, report)
    report["warmup"] = warmup
    model_info = _model_info_for_engine(engine)
    if model_info is not None:
        report["model"] = asdict(model_info)

    if args.output:
        write_benchmark_report(report, args.output)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _compare_models(args: argparse.Namespace) -> int:
    """Run multiple Ollama models and write detailed and summary reports."""

    try:
        host = _resolve_ollama_host(args)
        load_prompt_template(args.prompt_version)
        model_manager = OllamaModelManager(
            OllamaModelManagerConfig(host=host, timeout_s=args.timeout_s)
        )
        installed_models = {model.model: model for model in model_manager.list_models()}
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OllamaModelManagementError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    suite = load_prompt_suite(args.prompts)
    output_dir = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    summary_experiment: dict[str, Any] | None = None
    for model in args.models:
        report_path = output_dir / f"{_model_slug(model)}.json"
        try:
            engine = OllamaReasoningEngine(
                OllamaConfig(
                    model=model,
                    host=host,
                    timeout_s=args.timeout_s,
                    prompt_version=args.prompt_version,
                    num_predict=args.num_predict,
                )
            )
            warmup = _warm_up_engine(
                engine,
                runs=args.warmup_runs,
                max_words=args.max_words,
            )
            report = run_reasoning_benchmark(
                engine,
                suite,
                max_words=args.max_words,
                evaluation_mode=args.evaluation_mode,
                repetitions=args.repetitions,
            )
        except OllamaReasoningError as exc:
            rows.append(failed_model_row(model, str(exc)))
            continue

        experiment = _experiment_metadata(args, suite, report)
        report["experiment"] = experiment
        report["warmup"] = warmup
        model_info = installed_models.get(model)
        if model_info is None:
            model_info = _model_info_for_engine(engine)
        if model_info is not None:
            report["model"] = asdict(model_info)
        else:
            report["model"] = {"model": model}
        write_benchmark_report(report, report_path)
        if summary_experiment is None:
            summary_experiment = experiment
        rows.append(
            summarize_benchmark_report(
                report,
                model=model,
                report_path=report_path,
            )
        )

    summary = write_comparison_summary(
        rows,
        output_dir=output_dir,
        experiment=summary_experiment,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if any(row.error is None for row in rows) else 1


def _warm_up_engine(
    engine: ReasoningEngine,
    *,
    runs: int,
    max_words: int,
) -> dict[str, Any]:
    """Warm a model without including those requests in benchmark latency."""

    latencies_ms: list[float] = []
    request = ReasoningRequest(
        transcript="Say hello briefly.",
        constraints=ReasoningConstraints(max_words=max_words),
    )
    for _ in range(runs):
        started = time.perf_counter()
        engine.generate(request)
        latencies_ms.append(round((time.perf_counter() - started) * 1000, 3))
    return {
        "runs": runs,
        "prompt": request.transcript,
        "latencies_ms": latencies_ms,
        "excluded_from_reported_latency": True,
    }


def _experiment_metadata(
    args: argparse.Namespace,
    suite: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Return settings and provenance needed to reproduce a benchmark run."""

    result_metadata = _first_result_metadata(report)
    suite_path = Path(args.prompts).resolve()
    return {
        "schema_version": 1,
        "suite": {
            "name": suite.get("name", "unnamed_reasoning_suite"),
            "path": _relative_path(suite_path),
            "sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            "case_count": report.get("total_cases"),
            "category_counts": report.get("suite", {}).get("category_counts", {}),
        },
        "generation": {
            "prompt_version": args.prompt_version,
            "output_format": result_metadata.get(
                "output_format",
                "structured_json",
            ),
            "temperature": _number(result_metadata.get("temperature")),
            "top_p": _number(result_metadata.get("top_p")),
            "num_ctx": _integer(result_metadata.get("num_ctx")),
            "num_predict": _integer(result_metadata.get("num_predict")),
            "max_predict_tokens": _integer(result_metadata.get("max_predict_tokens")),
            "max_words": args.max_words,
            "keep_alive": result_metadata.get("keep_alive"),
            "seed": None,
            "timeout_s": args.timeout_s,
        },
        "execution": {
            "evaluation_mode": args.evaluation_mode,
            "repetitions": args.repetitions,
            "warmup_runs": args.warmup_runs,
            "case_order": "fixed_suite_order_per_repetition",
            "total_responses_per_model": report.get("total_responses"),
        },
        "software": {
            "git_commit": _command_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
            ),
            "git_tracked_changes_present": bool(
                _command_output(
                    ["git", "status", "--porcelain", "--untracked-files=no"],
                    cwd=REPO_ROOT,
                )
            ),
            "python": platform.python_version(),
            "ollama_python": _package_version("ollama"),
            "ollama_cli": _command_output(["ollama", "--version"]),
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "logical_cpu_count": os.cpu_count(),
            "system_memory_bytes": psutil.virtual_memory().total,
        },
        "scoring": report.get("scoring", {}),
        "latency": {
            **report.get("latency", {}),
            "warmup_excluded": True,
        },
    }


def _model_info_for_engine(engine: ReasoningEngine) -> LocalModelInfo | None:
    if not isinstance(engine, OllamaReasoningEngine):
        return None
    try:
        manager = OllamaModelManager(
            OllamaModelManagerConfig(
                host=engine.config.host,
                timeout_s=engine.config.timeout_s,
            )
        )
        return next(
            (
                model
                for model in manager.list_models()
                if model.model == engine.config.model
            ),
            None,
        )
    except OllamaModelManagementError:
        return None


def _first_result_metadata(report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, list) or not results:
        return {}
    metadata = results[0].get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _command_output(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output or None


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (
        REPO_ROOT / "benchmarks" / "reasoning" / "results" / f"model-comparison-{stamp}"
    )


def _model_slug(model: str) -> str:
    """Convert a model name into a safe report filename stem."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
