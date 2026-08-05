"""Debounce wrapper that suppresses one-off command mis-recognitions.

Without acoustic echo cancellation, the microphone hears the assistant's own
playback, and a grammar-constrained recognizer can briefly map that audio to a
command (for example a spurious "stop"). This wrapper only forwards a command
once the inner spotter has reported the same command `confirm` times within a
window of `window` frames, so a fleeting single hit is ignored while a command
the user actually sustains still gets through.
"""

# Local
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.types import CommandEvent, PlaybackCommand

DEFAULT_CONFIRM: int = 2  # matching recognitions needed to emit
DEFAULT_WINDOW: int = 10  # frames without a match before the streak resets


class DebouncingCommandSpotter:
    """A CommandSpotter that only emits a command confirmed across frames."""

    def __init__(
        self,
        inner: CommandSpotter,
        *,
        confirm: int = DEFAULT_CONFIRM,
        window: int = DEFAULT_WINDOW,
    ) -> None:
        self._inner = inner
        self._confirm = confirm
        self._window = window
        self._command: PlaybackCommand | None = None
        self._count = 0
        self._idle = 0  # frames since the last matching recognition

    def process(self, frame: bytes) -> CommandEvent | None:
        """Forward one frame; emit a command only once it is confirmed."""
        event = self._inner.process(frame)
        if event is None:
            self._idle += 1
            if self._idle >= self._window:
                self._reset()
            return None
        if event.command == self._command:
            self._count += 1
        else:
            self._command = event.command
            self._count = 1
        self._idle = 0
        if self._count >= self._confirm:
            self._reset()
            return event
        return None

    def _reset(self) -> None:
        self._command = None
        self._count = 0
        self._idle = 0
