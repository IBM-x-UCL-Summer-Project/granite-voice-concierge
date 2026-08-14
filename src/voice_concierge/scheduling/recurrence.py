"""Work out when a repeating reminder fires next.

Pure arithmetic over epoch seconds: no clock of its own, no storage, no I/O.
Every function takes the current time as an argument, so the awkward cases (a
reminder that was due while the machine was asleep, one whose time has already
passed today) are ordinary tests rather than something that can only be
observed by waiting.

Daily and weekly repeats are advanced in local wall-clock time, because "every
morning at eight" means eight o'clock as the person experiences it, and adding a
fixed 86400 seconds would drift by an hour across a daylight-saving change.
"""

# Standard library
from datetime import datetime, timedelta, timezone

# Local
from voice_concierge.scheduling.types import Schedule

_DAY_SECONDS = 86_400


def next_occurrence(schedule: Schedule, after: int) -> int | None:
    """Return when this schedule next fires strictly after `after`.

    None means it never fires again, which is the case for a one-off reminder
    that has already been delivered.
    """
    if not schedule.repeats:
        return None
    if schedule.recurrence == "interval":
        return _next_interval(schedule, after)
    if schedule.recurrence == "daily":
        return _next_daily(schedule, after)
    return _next_weekly(schedule, after)


def _next_interval(schedule: Schedule, after: int) -> int:
    """Advance by whole intervals until past `after`.

    Jumping straight to the next future slot, rather than stepping one interval
    at a time, keeps a reminder that was missed for a week from firing hundreds
    of times to catch up.
    """
    step = schedule.interval_seconds or 0
    elapsed = after - schedule.due_at
    if elapsed < 0:
        return schedule.due_at
    return schedule.due_at + step * (elapsed // step + 1)


def _next_daily(schedule: Schedule, after: int) -> int:
    """Keep the local time of day, moving to the next day that is still ahead."""
    due = _to_local(schedule.due_at)
    candidate = _to_local(after).replace(
        hour=due.hour, minute=due.minute, second=due.second, microsecond=0
    )
    if _to_epoch(candidate) <= after:
        candidate += timedelta(days=1)
    return _to_epoch(candidate)


def _next_weekly(schedule: Schedule, after: int) -> int:
    """Keep the local time of day, on the next matching weekday."""
    due = _to_local(schedule.due_at)
    current = _to_local(after)
    candidate = current.replace(
        hour=due.hour, minute=due.minute, second=due.second, microsecond=0
    )
    target = schedule.weekday if schedule.weekday is not None else due.weekday()
    days_ahead = (target - candidate.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if _to_epoch(candidate) <= after:
        candidate += timedelta(days=7)
    return _to_epoch(candidate)


def advance(schedule: Schedule, after: int) -> Schedule | None:
    """Return the same schedule moved to its next firing, or None if finished."""
    upcoming = next_occurrence(schedule, after)
    if upcoming is None:
        return None
    return Schedule(
        due_at=upcoming,
        recurrence=schedule.recurrence,
        interval_seconds=schedule.interval_seconds,
        weekday=schedule.weekday,
    )


def seconds_until(due_at: int, now: int) -> int:
    """Whole seconds until a due time, never negative."""
    return max(0, due_at - now)


def describe_delay(seconds: int) -> str:
    """Describe a duration the way a person would say it.

    Used when confirming a new reminder aloud, where "in two hours" is a far
    better acknowledgement than an absolute timestamp the user then has to
    compare against the clock.
    """
    if seconds < 60:
        return f"{seconds} seconds" if seconds != 1 else "1 second"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes" if minutes != 1 else "1 minute"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours" if hours != 1 else "1 hour"
    days = hours // 24
    return f"{days} days" if days != 1 else "1 day"


def _to_local(epoch: int) -> datetime:
    """Turn epoch seconds into local wall-clock time."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()


def _to_epoch(moment: datetime) -> int:
    """Turn a local wall-clock time back into epoch seconds."""
    return int(moment.timestamp())
