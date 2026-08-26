"""Run the component and whole-pipeline benchmark suite.

One command produces one dated JSON record and one Markdown report:

    python -m benchmarks.suite --tts piper

A stage that cannot run is skipped and named in the report rather than
aborting the run, so a machine without Ollama still produces the speech
results. The one thing that does abort is a text-to-speech backend that was
asked for by name and cannot synthesize: substituting a different voice there
would silently mislabel every number downstream.
"""

from __future__ import annotations

# Standard library
import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

# Local
from benchmarks.suite import components, pipeline, report
from benchmarks.suite.backends import (
    BACKEND_CHOICES,
    BackendUnavailableError,
    resolve_backend,
)
from benchmarks.suite.harness import (
    REPO_ROOT,
    describe_device,
    describe_provenance,
    eprint,
    package_versions,
)

#: Stages in the order they run. Speech stages come first so a run without a
#: local model server still produces most of the report.
STAGE_NAMES: tuple[str, ...] = (
    "tts",
    "stt",
    "wake_word",
    "vad",
    "reasoning",
    "pipeline",
)

#: Distributions whose versions change the numbers enough to be worth pinning
#: to a run.
TRACKED_PACKAGES: tuple[str, ...] = (
    "piper-tts",
    "faster-whisper",
    "openwakeword",
    "onnxruntime",
    "silero-vad",
    "torch",
    "vosk",
    "ollama",
    "numpy",
)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "benchmarks/suite/results"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.suite",
        description="Benchmark every voice pipeline component and the whole pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m benchmarks.suite --tts piper\n"
            "  python -m benchmarks.suite --tts piper --only tts stt\n"
            "  python -m benchmarks.suite --tts auto --skip reasoning pipeline\n"
            "  python -m benchmarks.suite --preflight-only\n"
        ),
    )
    parser.add_argument(
        "--tts",
        choices=BACKEND_CHOICES,
        default="piper",
        help=(
            "Text-to-speech backend to measure with. An explicit choice is "
            "never silently substituted; 'auto' picks the first that works and "
            "reports which. Default: piper."
        ),
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=STAGE_NAMES,
        help="Run only these stages.",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        choices=STAGE_NAMES,
        default=(),
        help="Skip these stages.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=8,
        help="Whole-pipeline turns to record. Default: 8.",
    )
    parser.add_argument(
        "--stt-model",
        help="Override the speech-to-text model size (e.g. small.en).",
    )
    parser.add_argument(
        "--recorded-dir",
        type=Path,
        nargs="+",
        default=(),
        help=(
            "Speaker folders of recorded speech to score, each holding a "
            "manifest written by `python -m benchmarks.suite.record`. Pass "
            "several to pool multiple speakers. This is the only figure in the "
            "suite that describes real voices."
        ),
    )
    parser.add_argument(
        "--reasoning-model",
        help="Override the reasoning model (e.g. granite3.3:2b).",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Run pipeline turns without the memory subsystem loaded.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write results. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--tag",
        help="Label appended to the output filenames, e.g. 'piper-rerun'.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check the environment and backends, then stop.",
    )
    return parser.parse_args(argv)


def selected_stages(args: argparse.Namespace) -> list[str]:
    """Resolve which stages to run from --only and --skip."""
    chosen = list(args.only) if args.only else list(STAGE_NAMES)
    return [stage for stage in chosen if stage not in set(args.skip)]


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def run_preflight() -> dict:
    """Report environment readiness without changing anything.

    Reuses the project's existing readiness checks so there is one definition
    of "this machine is set up", rather than a second that drifts from it.
    """
    try:
        from benchmarks.app.readiness import run_readiness_checks
    except ImportError as exc:  # pragma: no cover - readiness module is present
        return {"available": False, "detail": str(exc), "checks": []}

    checks = run_readiness_checks(check_audio_devices=False)
    rendered = [
        {
            "name": check.name,
            "status": check.status,
            "detail": check.detail,
            "remediation": check.remediation,
        }
        for check in checks
    ]
    failures = [check for check in rendered if check["status"] == "fail"]
    return {
        "available": True,
        "checks": rendered,
        "failures": len(failures),
    }


def _print_preflight(preflight: dict) -> None:
    """Show readiness results, worst first."""
    if not preflight.get("available"):
        eprint(f"Preflight unavailable: {preflight.get('detail')}")
        return
    order = {"fail": 0, "warn": 1, "pass": 2}
    checks = sorted(preflight["checks"], key=lambda c: order.get(c["status"], 3))
    for check in checks:
        if check["status"] == "pass":
            continue
        eprint(f"  [{check['status'].upper():4}] {check['name']}: {check['detail']}")
        if check["remediation"]:
            eprint(f"         fix: {check['remediation']}")
    passed = sum(1 for c in checks if c["status"] == "pass")
    eprint(f"  {passed}/{len(checks)} readiness checks passed.")


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def _run_stage(
    name: str,
    operation: Callable[[], dict],
    results: dict,
    destination: dict,
) -> None:
    """Run one stage, recording a failure instead of aborting the suite.

    A missing model server should cost the reasoning numbers, not the speech
    ones. Whatever fails is named in the report so a partial run cannot be
    mistaken for a complete one.
    """
    try:
        destination[name] = operation()
    except Exception as exc:
        results.setdefault("skipped", {})[name] = f"{type(exc).__name__}: {exc}"
        eprint(f"  ! {name} did not run: {type(exc).__name__}: {exc}")
        if not isinstance(exc, (RuntimeError, OSError, ImportError, ValueError)):
            traceback.print_exc(file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    stages = selected_stages(args)

    eprint("Preflight ...")
    preflight = run_preflight()
    _print_preflight(preflight)

    eprint(f"Resolving text-to-speech backend (requested: {args.tts}) ...")
    try:
        backend_name, backend, probes = resolve_backend(args.tts)
    except BackendUnavailableError as exc:
        eprint(f"\n{exc}\n")
        return 2
    selected_probe = next(
        (probe for probe in probes if probe.name == backend_name), None
    )
    eprint(f"  using: {backend_name}")

    if args.preflight_only:
        eprint("\nPreflight only — stopping before measurement.")
        return 0

    results: dict = {
        "provenance": describe_provenance(),
        "device": describe_device(),
        "versions": package_versions(TRACKED_PACKAGES),
        "preflight": preflight,
        "text_to_speech": {
            "requested": args.tts,
            "selected": backend_name,
            "detail": selected_probe.detail if selected_probe else "",
            "probes": [probe.as_dict() for probe in probes],
        },
        "stages_requested": stages,
        "components": {},
    }

    eprint("\nMeasuring components ...")
    if "tts" in stages:
        _run_stage(
            "text_to_speech",
            lambda: components.benchmark_tts(backend_name, backend),
            results,
            results["components"],
        )
    if "stt" in stages:
        _run_stage(
            "speech_to_text",
            lambda: components.benchmark_stt(
                backend,
                model_size=args.stt_model,
                recorded_dirs=args.recorded_dir,
            ),
            results,
            results["components"],
        )
    if "wake_word" in stages:
        _run_stage(
            "wake_word",
            lambda: components.benchmark_wake_word(backend),
            results,
            results["components"],
        )
    if "vad" in stages:
        _run_stage(
            "voice_activity_detection",
            lambda: components.benchmark_vad(backend),
            results,
            results["components"],
        )
    if "reasoning" in stages:
        _run_stage(
            "reasoning",
            lambda: components.benchmark_reasoning(model=args.reasoning_model),
            results,
            results["components"],
        )

    if "pipeline" in stages:
        eprint("\nMeasuring whole pipeline ...")
        _run_stage(
            "pipeline",
            lambda: pipeline.benchmark_pipeline(
                backend_name,
                backend,
                turns=args.turns,
                load_memory=not args.no_memory,
                reasoning_model=args.reasoning_model,
            ),
            results,
            results,
        )

    json_path, markdown_path = _output_paths(args, backend_name)
    report.write_json(json_path, results)
    report.write_markdown(markdown_path, results)

    eprint("\nDone.")
    eprint(f"  {markdown_path}")
    eprint(f"  {json_path}")
    if results.get("skipped"):
        eprint(f"\n  {len(results['skipped'])} stage(s) did not run — see the report.")
    print(markdown_path)
    return 0


def _output_paths(args: argparse.Namespace, backend_name: str) -> tuple[Path, Path]:
    """Build dated, backend-labelled output paths.

    The backend goes in the filename so two runs measuring different voices
    cannot be confused for one another later.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{args.tag}" if args.tag else ""
    stem = f"{stamp}-{backend_name}{suffix}"
    return (
        args.output_dir / f"{stem}.json",
        args.output_dir / f"{stem}.md",
    )


if __name__ == "__main__":
    sys.exit(main())
