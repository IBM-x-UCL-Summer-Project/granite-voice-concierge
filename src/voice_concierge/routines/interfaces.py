"""Protocols for routine step sources and for running a routine hands-free."""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.types import Routine


@runtime_checkable
class RoutineProvider(Protocol):
    """Supplies a routine for a spoken request, or None if it has none."""

    def get_routine(self, request: str) -> Routine | None:
        """Return a routine matching the request, or None."""


@runtime_checkable
class StepSpeaker(Protocol):
    """Speaks a step aloud while staying interruptible."""

    def speak(self, text: str) -> CommandEvent | None:
        """Speak the text, returning a command that interrupted it, or None.

        Returning None means the text was spoken to the end (or was only paused
        and resumed), so the caller decides what happens next.
        """


@runtime_checkable
class CommandWaiter(Protocol):
    """Listens for a spoken command in the quiet gap between steps."""

    def wait(self, timeout: float) -> CommandEvent | None:
        """Wait up to timeout seconds for a command; None if none was heard."""
