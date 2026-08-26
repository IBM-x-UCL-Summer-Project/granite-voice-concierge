"""Guided recorder for real-voice speech-to-text material.

    python -m benchmarks.suite.record --speaker alice

Prompts one line at a time, records it, and writes the audio next to a
manifest pairing every file with the exact words that were read. The pairing
is the whole point: a word error rate is only as trustworthy as the alignment
between audio and reference, and a folder of WAVs plus a hand-written
transcript is one copy-paste away from being silently wrong.

Recording is resumable. Interrupt it and run the same command again, and it
picks up at the first line that has no audio.
"""

from __future__ import annotations

# Standard library
import argparse
import json
import sys
import threading
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Third-party
import numpy as np

# Local
from benchmarks.suite import corpus
from benchmarks.suite.harness import REPO_ROOT

DEFAULT_RECORDINGS_DIR = REPO_ROOT / "benchmarks/suite/recordings"
MANIFEST_NAME = "manifest.json"

#: 16 kHz mono is what the speech-to-text stage consumes, so recording at that
#: rate avoids a resample between the microphone and the measurement.
SAMPLE_RATE: int = 16000
CHANNELS: int = 1
FRAMES_PER_BUFFER: int = 1024

#: Read aloud in this order. The command set is what the assistant is built to
#: hear; the conversational lines are longer and closer to how someone actually
#: speaks to an assistant, and they carry most of the reference words.
SCRIPT: tuple[str, ...] = corpus.COMMAND_REQUESTS + corpus.CONVERSATIONAL_REQUESTS


@dataclass
class Manifest:
    """Recorded material for one speaker."""

    speaker: str
    metadata: dict
    sample_rate: int
    utterances: list[dict]

    def as_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "metadata": self.metadata,
            "sample_rate": self.sample_rate,
            "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "utterances": self.utterances,
        }


def load_manifest(directory: Path) -> dict | None:
    """Read a speaker's manifest, or None when there is not one yet."""
    path = directory / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def save_manifest(directory: Path, manifest: Manifest) -> None:
    """Write the manifest beside the audio."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest.as_dict(), indent=2))


class _Recorder:
    """Capture microphone audio between two key presses."""

    def __init__(self) -> None:
        from voice_concierge.audio.source import PyAudioSource

        self._source = PyAudioSource(
            rate=SAMPLE_RATE, channels=CHANNELS, frames_per_buffer=FRAMES_PER_BUFFER
        )

    def record_until_enter(self) -> np.ndarray:
        """Record on a background thread while the main thread waits for Enter."""
        frames: list[bytes] = []
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                try:
                    frames.append(self._source.read(FRAMES_PER_BUFFER))
                except Exception:  # pragma: no cover - device removed mid-record
                    break

        self._source.open()
        worker = threading.Thread(target=loop, daemon=True)
        worker.start()
        try:
            input()
        finally:
            stop.set()
            worker.join(timeout=2.0)
            self._source.close()

        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.frombuffer(b"".join(frames), dtype=np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    """Write mono 16-bit PCM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.astype(np.int16).tobytes())


def _describe(samples: np.ndarray) -> str:
    """Summarize a take so the speaker can tell silence from speech."""
    if samples.size == 0:
        return "nothing recorded"
    seconds = samples.size / SAMPLE_RATE
    peak = int(np.abs(samples).max())
    # 16-bit full scale is 32767; a peak this low means the mic heard room tone.
    level = "VERY QUIET" if peak < 1500 else "ok"
    return f"{seconds:.1f}s, peak {peak}/32767 ({level})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.suite.record",
        description="Record the speech-to-text script for one speaker.",
    )
    parser.add_argument(
        "--speaker",
        required=True,
        help="Short identifier for this speaker, e.g. 'alice'. Names the folder.",
    )
    parser.add_argument(
        "--age-band",
        help="Optional, e.g. '18-24' or '65+'. Recorded in the manifest.",
    )
    parser.add_argument(
        "--accent",
        help="Optional, e.g. 'southern British English'. Recorded in the manifest.",
    )
    parser.add_argument(
        "--notes",
        help="Optional notes, e.g. 'quiet room' or 'kitchen extractor running'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_RECORDINGS_DIR,
        help=f"Where speaker folders live. Default: {DEFAULT_RECORDINGS_DIR}",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard any existing takes for this speaker and start over.",
    )
    args = parser.parse_args(argv)

    directory = args.output_dir / args.speaker
    existing = None if args.restart else load_manifest(directory)
    done = {
        utterance["reference"]: utterance
        for utterance in (existing or {}).get("utterances", [])
        if (directory / utterance["file"]).is_file()
    }

    _print_intro(args.speaker, len(SCRIPT), len(done))

    recorder = _Recorder()
    utterances: list[dict] = []
    for index, reference in enumerate(SCRIPT, start=1):
        filename = f"{index:03d}.wav"
        if reference in done:
            utterances.append(done[reference])
            continue
        result = _record_one(recorder, directory, filename, reference, index)
        if result is None:
            print(
                "\nStopped. Run the same command again to carry on where you left off."
            )
            break
        if result:
            utterances.append(result)
        save_manifest(
            directory,
            Manifest(
                speaker=args.speaker,
                metadata={
                    "age_band": args.age_band,
                    "accent": args.accent,
                    "notes": args.notes,
                },
                sample_rate=SAMPLE_RATE,
                utterances=utterances,
            ),
        )

    print(f"\n{len(utterances)}/{len(SCRIPT)} lines recorded in {directory}")
    if len(utterances) == len(SCRIPT):
        print("\nAll done. Score it with:")
        print(f"  python -m benchmarks.suite --tts piper --recorded-dir {directory}")
    return 0


def _print_intro(speaker: str, total: int, already_done: int) -> None:
    print(f"\nRecording {total} lines for speaker {speaker!r}.")
    if already_done:
        print(f"{already_done} already recorded — carrying on from there.")
    print(
        "\nRead each line exactly as written, at your normal speaking pace.\n"
        "Do not correct yourself mid-line: if you fumble it, redo the take.\n"
        "A quiet room is ideal, but a normal room is fine — say so in --notes.\n"
    )


def _record_one(
    recorder: _Recorder,
    directory: Path,
    filename: str,
    reference: str,
    index: int,
) -> dict | None:
    """Record one line, allowing retakes. Returns None if the user quits."""
    while True:
        print(f'\n[{index:>2}/{len(SCRIPT)}]  "{reference}"')
        try:
            input("       Enter to start recording ...")
        except (EOFError, KeyboardInterrupt):
            return None

        print("       RECORDING — Enter to stop.")
        try:
            samples = recorder.record_until_enter()
        except (EOFError, KeyboardInterrupt):
            return None

        print(f"       captured {_describe(samples)}")
        try:
            choice = input(
                "       Enter to keep, 'r' to redo, 's' to skip, 'q' to quit: "
            )
        except (EOFError, KeyboardInterrupt):
            return None

        choice = choice.strip().lower()
        if choice == "q":
            return None
        if choice == "r":
            continue
        if choice == "s":
            return {}
        if samples.size == 0:
            print("       nothing was recorded — redoing.")
            continue
        write_wav(directory / filename, samples)
        return {"file": filename, "reference": reference}


if __name__ == "__main__":
    sys.exit(main())
