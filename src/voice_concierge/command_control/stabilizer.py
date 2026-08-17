"""Stabilize a noisy command spotter into confident, de-duplicated commands.

A grammar-constrained recognizer emits from partial results so a command can
interrupt playback in time (see VoskPhraseRecognizer). That low latency costs
accuracy in two ways:

* it fleetingly maps noise or the beginning of a word to the wrong grammar
  word, firing a command nobody spoke;
* it surfaces one spoken word two or three times (the partial, then the final,
  then the word's trailing audio in the next listening context), so a single
  "back" navigates twice.

This wrapper fixes both without slowing a real command down noticeably. A
command must remain unchanged for `required_sightings` observations within
`confirm_window` before it is emitted, which drops an early hypothesis that
Vosk corrects as more audio arrives. Once emitted, the same command is refused
for `cooldown`, which drops the repeats. A command genuinely spoken again after
the cooldown still gets through.

Thresholds are in seconds rather than frame counts so they hold whatever frame
size the caller streams, and the clock is injectable so tests stay deterministic.
Unlike DebouncingCommandSpotter, which counts frames and resets on a gap of
silence, nothing here can be reset early by a stray silent frame.
"""

# Standard library
import time
from collections.abc import Callable

# Local
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.types import CommandEvent, VoiceCommand

DEFAULT_CONFIRM_WINDOW: float = 1.0  # seconds in which a command must recur to fire
DEFAULT_COOLDOWN: float = 1.5  # seconds the same command is refused after firing
DEFAULT_REQUIRED_SIGHTINGS: int = 3  # matching recognitions needed to emit


class StableCommandSpotter:
    """A CommandSpotter that emits only confirmed, non-repeated commands."""

    def __init__(
        self,
        inner: CommandSpotter,
        *,
        confirm_window: float = DEFAULT_CONFIRM_WINDOW,
        cooldown: float = DEFAULT_COOLDOWN,
        required_sightings: int = DEFAULT_REQUIRED_SIGHTINGS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if required_sightings < 1:
            raise ValueError("required_sightings must be at least one.")
        self._inner = inner
        self._confirm_window = confirm_window
        self._cooldown = cooldown
        self._required_sightings = required_sightings
        self._clock = clock
        self._pending: VoiceCommand | None = None
        self._pending_at = 0.0
        self._pending_sightings = 0
        self._emitted: VoiceCommand | None = None
        self._emitted_at = 0.0

    def process(self, frame: bytes) -> CommandEvent | None:
        """Forward one frame; emit a command only once it is confirmed and new."""
        event = self._inner.process(frame)
        if event is None:
            return None
        command = event.command
        now = self._clock()
        if command == self._emitted and now - self._emitted_at < self._cooldown:
            return None  # already acted on this command; a repeat of it
        if self._required_sightings == 1:
            return self._emit(event, now)
        if command == self._pending and now - self._pending_at <= self._confirm_window:
            self._pending_sightings += 1
            if self._pending_sightings >= self._required_sightings:
                return self._emit(event, now)
            return None
        self._pending, self._pending_at = command, now
        self._pending_sightings = 1
        return None  # first sighting: wait for confirmation

    def _emit(self, event: CommandEvent, now: float) -> CommandEvent:
        """Emit one command and discard the rest of its recognizer utterance."""

        self._pending = None
        self._pending_sightings = 0
        self._emitted, self._emitted_at = event.command, now
        self._reset_inner()
        return event

    def _reset_inner(self) -> None:
        reset = getattr(self._inner, "reset", None)
        if callable(reset):
            reset()

    def reset(self) -> None:
        """Discard pending and cooldown state at a trusted audio boundary."""

        self._pending = None
        self._pending_at = 0.0
        self._pending_sightings = 0
        self._emitted = None
        self._emitted_at = 0.0
        self._reset_inner()
