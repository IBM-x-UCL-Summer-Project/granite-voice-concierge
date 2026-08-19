"""ReminderService - create, list, cancel and deliver reminders.

Holds the rules that sit between storage and whatever is doing the announcing:
what counts as due, what happens to a reminder once it has been delivered, and
what to say when one is set.

The clock is injectable, so "a reminder that came due while the machine was
asleep" is an ordinary test rather than something only observable by waiting.
"""

# Standard library
import time
from collections.abc import Callable
from dataclasses import replace

# Local
from voice_concierge.scheduling.errors import SchedulingError
from voice_concierge.scheduling.parser import parse_reminder
from voice_concierge.scheduling.recurrence import advance, describe_delay
from voice_concierge.scheduling.store import ReminderStore
from voice_concierge.scheduling.types import Reminder

_NO_TIME = "I didn't catch a time for that. Try 'remind me to stretch in ten minutes'."


class ReminderService:
    """The rules for keeping and delivering reminders."""

    def __init__(
        self,
        store: ReminderStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._clock = clock

    def now(self) -> int:
        """The current time as UTC epoch seconds."""
        return int(self._clock())

    def create_from_speech(self, transcript: str) -> Reminder | None:
        """Parse a spoken request and store it, or None if it had no time.

        None is a real answer, not a failure: the caller asks for a time rather
        than scheduling one it guessed.
        """
        parsed = parse_reminder(transcript, now=self.now())
        if parsed is None:
            return None
        return self._store.add(parsed, now=self.now())

    def confirmation(self, reminder: Reminder | None) -> str:
        """What to say back when a reminder has just been set.

        Always states when it will happen, so a misheard time is caught at the
        moment it is set rather than when it fails to arrive.
        """
        if reminder is None:
            return _NO_TIME
        delay = describe_delay(max(0, reminder.due_at - self.now()))
        if reminder.kind == "timer":
            return f"Timer set for {delay}."
        if reminder.schedule.recurrence == "interval":
            return f"I'll remind you to {reminder.text} every {delay}."
        if reminder.schedule.repeats:
            return (
                f"I'll remind you to {reminder.text}, "
                f"{reminder.schedule.recurrence}, starting in {delay}."
            )
        return f"I'll remind you to {reminder.text} in {delay}."

    def due(self, *, now: int | None = None) -> tuple[Reminder, ...]:
        """Reminders that have come due and not yet been delivered.

        Includes any that fell due while the assistant was not running. A
        missed medication reminder is worth announcing late; silently skipping
        it is the one outcome this package exists to avoid.
        """
        moment = self.now() if now is None else now
        return tuple(
            reminder
            for reminder in self._store.list_pending()
            if reminder.due_at <= moment
        )

    def acknowledge(self, reminder: Reminder, *, now: int | None = None) -> None:
        """Record that a reminder was delivered, and set up any repeat."""
        if reminder.identifier is None:
            raise SchedulingError("An unsaved reminder cannot be acknowledged.")
        moment = self.now() if now is None else now
        upcoming = advance(reminder.schedule, moment)
        if upcoming is None:
            self._store.complete(reminder.identifier)
            return
        self._store.reschedule(reminder.identifier, upcoming)

    def upcoming(self) -> tuple[Reminder, ...]:
        """Every reminder still waiting, soonest first."""
        return self._store.list_pending()

    def cancel(self, identifier: int) -> None:
        """Remove one reminder, raising if there was nothing to remove."""
        if not self._store.delete(identifier):
            raise SchedulingError(f"No reminder with id {identifier} is set.")

    def edit(
        self,
        identifier: int,
        *,
        text: str | None = None,
        due_at: int | None = None,
    ) -> Reminder:
        """Change the wording or next due time of one pending reminder."""

        reminder = self._store.get(identifier)
        if reminder is None or reminder.completed:
            raise SchedulingError(f"No pending reminder with id {identifier} is set.")
        updated_text = reminder.text if text is None else text.strip()
        if not updated_text:
            raise SchedulingError("A reminder needs something to say.")
        updated_due_at = reminder.due_at if due_at is None else due_at
        if not isinstance(updated_due_at, int) or isinstance(updated_due_at, bool):
            raise SchedulingError("Reminder due_at must be an integer timestamp.")
        updated = replace(
            reminder,
            text=updated_text,
            schedule=replace(reminder.schedule, due_at=updated_due_at),
        )
        return self._store.update(updated)

    def snooze(self, identifier: int, seconds: int) -> Reminder:
        """Move the next occurrence forward from now by a positive duration."""

        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            raise SchedulingError(
                "Snooze duration must be a positive number of seconds."
            )
        return self.edit(identifier, due_at=self.now() + seconds)

    def cancel_all(self) -> int:
        """Remove every reminder, returning how many were removed."""
        return self._store.delete_all()

    def close(self) -> None:
        """Release the underlying store."""
        self._store.close()
