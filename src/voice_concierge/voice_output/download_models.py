"""Download Piper voice assets for local, offline synthesis."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from piper.download_voices import download_voice, list_voices

from voice_concierge.voice_output.piper import (
    DEFAULT_MODEL_DIRECTORY,
    DEFAULT_VOICE,
    resolve_piper_voice_paths,
)

LOGGER = logging.getLogger(__name__)


def download_piper_voices(
    voices: Sequence[str],
    output_directory: Path | str = DEFAULT_MODEL_DIRECTORY,
    *,
    downloader: Callable[[str, Path], None] = download_voice,
) -> tuple[tuple[Path, Path], ...]:
    """Download selected voices with Piper's maintained catalogue client."""

    if not voices:
        raise ValueError("At least one Piper voice must be selected.")
    directory = Path(output_directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    downloaded: list[tuple[Path, Path]] = []
    for voice in voices:
        model_path, config_path = resolve_piper_voice_paths(voice, directory)
        LOGGER.info("Preparing Piper voice %s in %s", voice, directory)
        downloader(voice, directory)
        downloaded.append((Path(model_path), Path(config_path)))
    return tuple(downloaded)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one or more Piper voices for local use.",
    )
    parser.add_argument(
        "voices",
        nargs="*",
        default=None,
        help=(
            "Piper identifiers such as en_GB-alan-medium. The project default "
            "is downloaded when none are supplied."
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
        help="Directory for the .onnx and .onnx.json voice assets.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List voices from the upstream Piper catalogue and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Piper voice downloader command."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.list:
        list_voices()
        return 0
    voices = args.voices or [DEFAULT_VOICE]
    try:
        download_piper_voices(voices, args.output_directory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
