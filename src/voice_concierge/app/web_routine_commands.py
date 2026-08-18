"""Session-safe voice command spotting for browser-streamed local audio."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.types import CommandEvent


class RoutineCommandSessionInactiveError(RuntimeError):
    """Raised when a stale browser sends audio outside an active command stream."""


class WebRoutineCommandService:
    """Own the command spotter shared by browser playback and routines."""

    def __init__(self, spotter_factory: Callable[[], CommandSpotter]) -> None:
        self._spotter_factory = spotter_factory
        self._spotter: CommandSpotter | None = None
        self._active_session_id: str | None = None
        self._lock = RLock()

    def start(self, session_id: str) -> None:
        """Start a clean stream while keeping the local model warm."""

        with self._lock:
            if self._spotter is None:
                self._spotter = self._spotter_factory()
            else:
                self._reset_spotter()
            self._active_session_id = session_id

    def stop(self, session_id: str | None) -> bool:
        """Stop this session without allowing stale tabs to stop another."""

        with self._lock:
            if session_id is None or session_id != self._active_session_id:
                return False
            self._active_session_id = None
            self._reset_spotter()
            return True

    def reset(self, session_id: str | None) -> None:
        """Discard prompt audio before accepting a confirmation answer."""

        with self._lock:
            if (
                session_id is None
                or session_id != self._active_session_id
                or self._spotter is None
            ):
                raise RoutineCommandSessionInactiveError(
                    "Routine command listening is not active for this browser session."
                )
            self._reset_spotter()

    def process_pcm(
        self,
        session_id: str | None,
        pcm: bytes,
    ) -> CommandEvent | None:
        """Return the first stable command found in a mono int16 PCM block."""

        if not pcm or len(pcm) % 2:
            raise ValueError("pcm must contain complete 16-bit samples.")
        with self._lock:
            if (
                session_id is None
                or session_id != self._active_session_id
                or self._spotter is None
            ):
                raise RoutineCommandSessionInactiveError(
                    "Routine command listening is not active for this browser session."
                )
            return self._spotter.process(pcm)

    def _reset_spotter(self) -> None:
        """Discard buffered speech without rebuilding the Vosk model."""

        if self._spotter is None:
            return
        reset = getattr(self._spotter, "reset", None)
        if callable(reset):
            reset()
        else:
            self._spotter = self._spotter_factory()
