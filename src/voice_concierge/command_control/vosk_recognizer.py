"""Vosk-backed phrase recognizer for command spotting."""

# Standard library
import json
from collections.abc import Iterable

# Local
from voice_concierge.command_control.errors import CommandSpotterUnavailableError

DEFAULT_MODEL_NAME: str = "vosk-model-small-en-us-0.15"
DEFAULT_SAMPLE_RATE: int = 16000


def _build_recognizer(model_name: str, sample_rate: int, grammar: str):
    """Build a grammar-constrained Vosk recognizer (vosk imported lazily).

    The model is downloaded and cached by Vosk on first use (under
    ``~/.cache/vosk``) when referenced by name, so no manual download is needed.
    """
    from vosk import KaldiRecognizer, Model

    return KaldiRecognizer(Model(model_name=model_name), sample_rate, grammar)


class VoskPhraseRecognizer:
    """PhraseRecognizer backed by a grammar-constrained Vosk recognizer."""

    def __init__(
        self,
        vocabulary: Iterable[str],
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        recognizer=None,
    ) -> None:
        if recognizer is not None:
            self._recognizer = recognizer
            return
        grammar = json.dumps([*vocabulary, "[unk]"])
        try:
            self._recognizer = _build_recognizer(model_name, sample_rate, grammar)
        except Exception as exc:
            raise CommandSpotterUnavailableError(
                f"Could not load Vosk model {model_name!r}: {exc}"
            ) from exc

    def recognize(self, frame: bytes) -> str | None:
        """Feed one frame to Vosk; return a finalized phrase or None."""
        if not self._recognizer.AcceptWaveform(frame):
            return None
        text = json.loads(self._recognizer.Result()).get("text", "").strip()
        return text or None
