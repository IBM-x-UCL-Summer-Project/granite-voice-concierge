"""Deterministic fakes for barge-in command control."""

# Standard library
from collections import deque
from collections.abc import Iterable

# Local
from voice_concierge.command_control.types import CommandEvent, PlaybackCommand


class FakeCommandSpotter:
    """CommandSpotter fake that emits scripted events on successive frames."""

    def __init__(self, events: Iterable[CommandEvent | None] = ()) -> None:
        self._events: deque[CommandEvent | None] = deque(events)
        self.frames: list[bytes] = []

    def process(self, frame: bytes) -> CommandEvent | None:
        """Record the frame and return the next scripted event, if any."""
        self.frames.append(frame)
        if self._events:
            return self._events.popleft()
        return None


class FakePlaybackController:
    """PlaybackController fake that records the actions it received."""

    def __init__(self) -> None:
        self.actions: list[PlaybackCommand] = []

    def stop(self) -> None:
        self.actions.append("stop")

    def pause(self) -> None:
        self.actions.append("pause")

    def resume(self) -> None:
        self.actions.append("resume")
