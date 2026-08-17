"""Removes the wake phrase from a transcript once it is inside the audio.

Retaining the audio from before the wake word fired is what makes a
single-sentence request possible, but it also means the wake phrase is now part
of what gets transcribed. Most of the app does not care: the routine and
reminder triggers match on substrings, so "hey jarvis, walk me through making
scrambled eggs" still contains "walk me through".

The context-mode matcher does care. It is anchored to the whole utterance, on
purpose, so that a passing mention of driving cannot silently change modes.
That anchoring means "switch to driving mode" stops matching the moment it
arrives with a wake phrase in front of it. Stripping the phrase here keeps that
deliberate strictness working instead of quietly loosening it.
"""

# Standard library
from dataclasses import dataclass

# Local
from voice_concierge.app.types import SpeechToTextAdapter, TranscriptResult
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.one_breath import strip_wake_phrase

#: Spoken forms of the wake word that a recogniser is likely to produce. The
#: bare name is included because recognisers often drop the "hey".
DEFAULT_WAKE_PHRASES: tuple[str, ...] = (
    "hey jarvis",
    "hey, jarvis",
    "hi jarvis",
    "jarvis",
)


@dataclass(frozen=True)
class StrippedTranscript:
    """A transcript with the wake phrase removed from the front."""

    text: str
    language: str | None = None
    language_probability: float | None = None


class WakePhraseStrippingSpeechToText:
    """Wraps an STT backend and drops a leading wake phrase from its output.

    Satisfies SpeechToTextAdapter, so the pipeline takes one without knowing
    that a wake phrase was ever in the audio.
    """

    def __init__(
        self,
        inner: SpeechToTextAdapter,
        *,
        phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
    ) -> None:
        self._inner = inner
        self._phrases = phrases

    def transcribe(self, audio: CapturedAudio) -> TranscriptResult:
        """Transcribe, then remove the wake phrase if the result opens with one."""
        result = self._inner.transcribe(audio)
        stripped = strip_wake_phrase(result.text, self._phrases)
        if stripped == result.text:
            # Nothing to change, so hand back the backend's own result rather
            # than a copy that might drop fields this wrapper does not know.
            return result

        return StrippedTranscript(
            text=stripped,
            language=result.language,
            language_probability=result.language_probability,
        )
