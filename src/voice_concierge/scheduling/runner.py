"""Deliver reminders when they come due, while the assistant is running.

Split deliberately in two. `check_once` is a plain function call that delivers
whatever is due right now and returns it, so every rule about delivery is
testable without threads or waiting. `ReminderRunner` is the thin wrapper that
calls it on a timer in the background.

A reminder is acknowledged only after the notifier has accepted it. If speaking
fails the reminder stays due, so a failure delays a reminder rather than
swallowing it.
"""

# Standard library
import threading
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.types import Reminder

DEFAULT_POLL_SECONDS: float = 5.0


@runtime_checkable
class Notifier(Protocol):
    """Announces a reminder that has come due."""

    def notify(self, reminder: Reminder) -> None:
        """Deliver the reminder. Raising leaves it due to try again."""


class PrintNotifier:
    """Notifier that writes to standard output, for testing and headless use."""

    def __init__(self, write: Callable[[str], None] = print) -> None:
        self._write = write

    def notify(self, reminder: Reminder) -> None:
        self._write(reminder.announcement)


def check_once(
    service: ReminderService, notifier: Notifier, *, now: int | None = None
) -> tuple[Reminder, ...]:
    """Deliver every reminder that is due, returning those delivered.

    A notifier that raises leaves its reminder untouched and does not stop the
    others: one broken announcement should not hold up the rest.
    """
    delivered: list[Reminder] = []
    for reminder in service.due(now=now):
        try:
            notifier.notify(reminder)
        except Exception:
            continue  # still due, so it will be retried on the next check
        service.acknowledge(reminder, now=now)
        delivered.append(reminder)
    return tuple(delivered)


class ReminderRunner:
    """Checks for due reminders on a timer, in a background thread."""

    def __init__(
        self,
        service: ReminderService,
        notifier: Notifier,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._service = service
        self._notifier = notifier
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Whether the background thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def check_now(self) -> tuple[Reminder, ...]:
        """Deliver anything due right now, without waiting for the timer."""
        return check_once(self._service, self._notifier)

    def start(self) -> None:
        """Begin checking in the background. Starting twice is harmless."""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        """Stop checking and wait briefly for the thread to finish.

        The join is bounded so a wedged check cannot hang the application on
        the way out.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def _loop(self) -> None:  # pragma: no cover - exercised via start/stop
        """Poll until stopped, ignoring a failed check so the loop survives."""
        while not self._stop.is_set():
            try:
                self.check_now()
            except Exception:
                pass  # a bad check must not end reminder delivery for the session
            self._stop.wait(self._poll_seconds)

    def __enter__(self) -> "ReminderRunner":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def wait_for(condition: Callable[[], bool], *, timeout: float = 2.0) -> bool:
    """Wait for a condition, for tests that need the background thread to run."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()
