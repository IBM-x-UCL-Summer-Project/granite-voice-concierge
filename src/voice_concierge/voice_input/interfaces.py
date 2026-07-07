"""Interfaces for the voice input pipeline stages."""

# Standard library
from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio import CapturedAudio


@runtime_checkable
class WakeWordListener(Protocol):
    """Listens for a wake word and fires a callback on detection."""

    def listen(self, on_wake_word: Callable[[], None]) -> None:
        """Listen until the wake word is detected, then call on_wake_word."""


@runtime_checkable
class UtteranceCapturer(Protocol):
    """Captures a spoken utterance and delivers it as CapturedAudio."""

    def capture_utterance(
        self, on_utterance_captured: Callable[[CapturedAudio], None]
    ) -> None:
        """Capture one utterance and pass it to on_utterance_captured."""
