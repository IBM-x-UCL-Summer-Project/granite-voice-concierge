"""Speech-to-text result types."""

# Standard library
from dataclasses import dataclass


@dataclass(frozen=True)
class Transcript:
    """Text produced by transcribing an utterance, with STT metadata."""

    #: Recognized text, stripped of leading/trailing whitespace.
    text: str
    #: Detected language code, when the backend reports one.
    language: str | None = None
    #: Backend confidence in the detected language, in [0, 1].
    language_probability: float | None = None
