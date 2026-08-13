"""Construction helpers for text-to-speech backends."""

# Standard library
from collections.abc import Callable
from pathlib import Path

# Local
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.pace_store import (
    DEFAULT_PACE_PATH,
    load_rate,
    save_rate,
)
from voice_concierge.voice_output.pacing import (
    DEFAULT_PACE_LEVEL,
    PACE_LADDER,
    PacedTextToSpeech,
    SpeechRate,
)
from voice_concierge.voice_output.piper import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LENGTH_SCALE,
    DEFAULT_MODEL_PATH,
    PiperTextToSpeech,
)


def build_text_to_speech(
    model_path: str = DEFAULT_MODEL_PATH,
    config_path: str = DEFAULT_CONFIG_PATH,
    *,
    length_scale: float = DEFAULT_LENGTH_SCALE,
) -> TextToSpeech:
    """Build the default local text-to-speech engine for application code."""
    return PiperTextToSpeech(model_path, config_path, length_scale=length_scale)


#: The rate the backends' own defaults correspond to, used to convert a rung of
#: the pace ladder into whatever unit a backend expresses speed in.
REFERENCE_WPM: int = PACE_LADDER[DEFAULT_PACE_LEVEL]


def piper_backend_builder(
    model_path: str = DEFAULT_MODEL_PATH,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> Callable[[int], TextToSpeech]:
    """Build Piper voices at a given words-per-minute.

    Piper expresses pace as a length scale, where larger is slower, so the
    requested rate is inverted against the reference rate.
    """

    def _build(rate_wpm: int) -> TextToSpeech:
        scale = DEFAULT_LENGTH_SCALE * REFERENCE_WPM / rate_wpm
        return PiperTextToSpeech(model_path, config_path, length_scale=scale)

    return _build


def say_backend_builder() -> Callable[[int], TextToSpeech]:
    """Build macOS `say` voices at a given words-per-minute.

    The `say` command takes a rate in words per minute directly, so a rung of
    the ladder passes straight through.
    """
    from voice_concierge.voice_output.say import SayTextToSpeech

    def _build(rate_wpm: int) -> TextToSpeech:
        return SayTextToSpeech(rate_wpm=rate_wpm)

    return _build


def build_paced_text_to_speech(
    build_backend: Callable[[int], TextToSpeech] | None = None,
    *,
    rate: SpeechRate | None = None,
    persist: bool = True,
    pace_path: Path | str = DEFAULT_PACE_PATH,
) -> PacedTextToSpeech:
    """Build a voice whose speaking rate the user can change by saying so.

    With persist set, the rate is restored from the last session and saved again
    whenever it changes, so someone who has asked the assistant to slow down
    does not have to ask again every time it starts. Saving is best effort: a
    preferences file that cannot be written costs the memory of the setting, not
    the ability to change it now.

    An explicit rate wins over the remembered one, which is what a caller
    forcing a rate for a test or a demo means.
    """
    starting = rate if rate is not None else (load_rate(pace_path) if persist else None)
    return PacedTextToSpeech(
        build_backend or piper_backend_builder(),
        rate=starting,
        on_change=(lambda moved: save_rate(moved, pace_path)) if persist else None,
    )
