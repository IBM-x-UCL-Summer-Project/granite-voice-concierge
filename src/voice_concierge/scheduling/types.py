"""Value types for reminders and timers.

Times are stored as UTC epoch seconds so a reminder means the same thing
whatever the process timezone is, and are only turned into local wall-clock
time at the point they are read out to a person.
"""

# Standard library
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

#: How a reminder repeats. "once" fires a single time and is then done.
Recurrence = Literal["once", "interval", "daily", "weekly"]

#: What a reminder is for. Timers are announced differently from reminders:
#: "your 10 minute timer is up" reads better than "reminder: 10 minutes".
Kind = Literal["reminder", "timer"]

#: Weekday names as spoken, in the order Python's weekday() numbers them.
WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class Schedule:
    """When a reminder fires, and whether it fires again.

    Deliberately narrower than a calendar rule: the cases a spoken assistant is
    actually asked for are "in ten minutes", "at eight", "every morning" and
    "every Tuesday". A full recurrence grammar would add states that could never
    be created by voice and could not be described back to the user clearly.
    """

    #: When this next fires, as UTC epoch seconds.
    due_at: int
    recurrence: Recurrence = "once"
    #: Seconds between repeats, for "interval" recurrence.
    interval_seconds: int | None = None
    #: Day of week (0 Monday to 6 Sunday), for "weekly" recurrence.
    weekday: int | None = None

    def __post_init__(self) -> None:
        # "is None" rather than falsy, so a supplied zero gets the clearer
        # "must be positive" message below instead of "needs interval_seconds".
        if self.recurrence == "interval" and self.interval_seconds is None:
            raise ValueError("An interval schedule needs interval_seconds.")
        if self.recurrence == "weekly" and self.weekday is None:
            raise ValueError("A weekly schedule needs a weekday.")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive.")
        if self.weekday is not None and not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be 0 (Monday) to 6 (Sunday).")

    @property
    def repeats(self) -> bool:
        """Whether this schedule fires more than once."""
        return self.recurrence != "once"


@dataclass(frozen=True)
class Reminder:
    """One reminder or timer, as stored and as read back to the user."""

    text: str
    schedule: Schedule
    kind: Kind = "reminder"
    identifier: int | None = None
    #: Set once the reminder has fired and will not fire again.
    completed: bool = False
    created_at: int | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("A reminder needs something to say.")

    @property
    def due_at(self) -> int:
        """When this next fires, as UTC epoch seconds."""
        return self.schedule.due_at

    def due_display(self, *, local_timezone: timezone | None = None) -> str:
        """The due time as local wall-clock text a person can act on."""
        moment = datetime.fromtimestamp(self.due_at, tz=timezone.utc)
        if local_timezone is not None:
            moment = moment.astimezone(local_timezone)
        else:
            moment = moment.astimezone()
        return moment.strftime("%a %d %b at %H:%M")

    @property
    def announcement(self) -> str:
        """What is said aloud when this fires."""
        if self.kind == "timer":
            return f"Your timer for {self.text} is up."
        return f"Reminder: {self.text}."
