"""Protocols for barge-in command control."""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.command_control.types import CommandEvent


@runtime_checkable
class CommandSpotter(Protocol):
    """Recognizes barge-in command words from streamed audio frames."""

    def process(self, frame: bytes) -> CommandEvent | None:
        """Process one audio frame, returning a command event when spotted."""


@runtime_checkable
class PlaybackController(Protocol):
    """Controls in-progress speech playback for barge-in."""

    def stop(self) -> None:
        """Stop playback immediately."""

    def pause(self) -> None:
        """Pause playback, retaining position for a later resume."""

    def resume(self) -> None:
        """Resume paused playback."""
