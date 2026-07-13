"""Vosk-backed phrase recognizer for command spotting."""

# Standard library
import json
from collections.abc import Iterable

# Local
from voice_concierge.command_control.errors import CommandSpotterUnavailableError

DEFAULT_MODEL_PATH: str = "vosk-model-small-en-us-0.15"
DEFAULT_SAMPLE_RATE: int = 16000


def _build_recognizer(model_path: str, sample_rate: int, grammar: str):
    """Build a grammar-constrained Vosk recognizer (vosk imported lazily)."""
    from vosk import KaldiRecognizer, Model

    return KaldiRecognizer(Model(model_path), sample_rate, grammar)


class VoskPhraseRecognizer:
    """PhraseRecognizer backed by a grammar-constrained Vosk recognizer."""

    def __init__(
        self,
        vocabulary: Iterable[str],
        *,
        model_path: str = DEFAULT_MODEL_PATH,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        recognizer=None,
    ) -> None:
        if recognizer is not None:
            self._recognizer = recognizer
            return
        grammar = json.dumps([*vocabulary, "[unk]"])
        try:
            self._recognizer = _build_recognizer(model_path, sample_rate, grammar)
        except Exception as exc:
            raise CommandSpotterUnavailableError(
                f"Could not load Vosk model at {model_path!r}: {exc}"
            ) from exc

    def recognize(self, frame: bytes) -> str | None:
        """Feed one frame to Vosk; return a finalized phrase or None."""
        if not self._recognizer.AcceptWaveform(frame):
            return None
        text = json.loads(self._recognizer.Result()).get("text", "").strip()
        return text or None
