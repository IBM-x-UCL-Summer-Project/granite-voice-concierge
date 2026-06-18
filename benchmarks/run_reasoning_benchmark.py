"""Run the local reasoning benchmark prompt suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from voice_concierge.reasoning import (  # noqa: E402
    DEFAULT_REASONING_MODEL,
    OllamaConfig,
    OllamaReasoningEngine,
    OllamaReasoningError,
    ReasoningEngine,
    RuleBasedReasoningPrototype,
)
from voice_concierge.reasoning.benchmark import (  # noqa: E402
    EVALUATION_MODES,
    load_prompt_suite,
    run_reasoning_benchmark,
    write_benchmark_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local reasoning prompts against a local reasoning engine.",
    )
    parser.add_argument(
        "--engine",
        choices=("prototype", "ollama"),
        default="prototype",
        help="Reasoning engine to benchmark.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_REASONING_MODEL,
        help="Local model name used when --engine ollama is selected.",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:11434",
        help="Ollama host URL for --engine ollama.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds for --engine ollama.",
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "reasoning_prompts_v0.json",
        help="Path to the reasoning prompt suite JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for writing the benchmark report JSON.",
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
        default="guarded",
        help=(
            "Evaluate raw model output, guarded product output, or both. "
            "Raw tracing is available for trace capable engines such as Ollama."
        ),
    )
    return parser.parse_args()


def build_engine(args: argparse.Namespace) -> ReasoningEngine:
    if args.engine == "prototype":
        return RuleBasedReasoningPrototype()

    if args.engine == "ollama":
        return OllamaReasoningEngine(
            OllamaConfig(
                model=args.model,
                host=args.host,
                timeout_s=args.timeout_s,
            )
        )

    raise ValueError(f"Unsupported engine: {args.engine}")


def main() -> int:
    args = parse_args()
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
    output = json.dumps(report, indent=2, sort_keys=True)

    if args.output:
        write_benchmark_report(report, args.output)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
