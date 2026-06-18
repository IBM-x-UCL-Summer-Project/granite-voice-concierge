"""Manage local reasoning models for the Ollama-backed prototype."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from voice_concierge.reasoning import (  # noqa: E402
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL_BACKEND,
    DEFAULT_OLLAMA_HOST,
    OllamaModelManagementError,
    OllamaModelManager,
    OllamaModelManagerConfig,
    ReasoningModelSelection,
    load_model_selection,
    save_model_selection,
)

DEFAULT_CONFIG_PATH = REPO_ROOT / ".local" / "reasoning-model-selection.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage local Ollama models for reasoning experiments.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the local model-selection config JSON.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        help="Ollama host URL.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=180.0,
        help="HTTP timeout in seconds for Ollama model-management requests.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("current", help="Print the active local model selection.")
    subparsers.add_parser("list", help="List locally installed Ollama models.")

    show_parser = subparsers.add_parser("show", help="Show details for one model.")
    show_parser.add_argument("model", help="Local model name to inspect.")

    pull_parser = subparsers.add_parser("pull", help="Pull a model through Ollama.")
    pull_parser.add_argument("model", help="Model name to download.")
    pull_parser.add_argument(
        "--stream",
        action="store_true",
        help="Print streamed download progress updates.",
    )

    select_parser = subparsers.add_parser("select", help="Persist active model choice.")
    select_parser.add_argument("model", help="Model to use as the active default.")
    select_parser.add_argument(
        "--fallback-model",
        default=DEFAULT_FALLBACK_MODEL,
        help="Fallback model to use on constrained hardware or failure.",
    )
    select_parser.add_argument(
        "--backend",
        default=DEFAULT_MODEL_BACKEND,
        help="Model backend name.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manager = OllamaModelManager(
        OllamaModelManagerConfig(host=args.host, timeout_s=args.timeout_s)
    )

    try:
        if args.command == "current":
            _print_json(asdict(load_model_selection(args.config)))
            return 0

        if args.command == "list":
            models = [asdict(model) for model in manager.list_models()]
            _print_json({"models": models})
            return 0

        if args.command == "show":
            details = manager.show_model(args.model)
            _print_json(asdict(details))
            return 0

        if args.command == "pull":
            progress = manager.pull_model(args.model, stream=args.stream)
            _print_json({"progress": [asdict(update) for update in progress]})
            return 0

        if args.command == "select":
            selection = ReasoningModelSelection(
                backend=args.backend,
                model=args.model,
                fallback_model=args.fallback_model,
                host=args.host,
            )
            save_model_selection(selection, args.config)
            _print_json(asdict(selection))
            return 0
    except (OllamaModelManagementError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Unsupported command: {args.command}", file=sys.stderr)
    return 2


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
