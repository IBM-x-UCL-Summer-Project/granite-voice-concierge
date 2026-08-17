"""Turn a spoken request into a reminder, or decline to guess.

Deliberately a rule-based parser rather than a model call. Three reasons: a
person setting a timer should not wait for inference; the same words must always
produce the same time, because a reminder that lands an hour out is worse than
one that was never set; and a rule set can refuse, whereas a model asked for a
time will always produce one.

Refusing is the important part. Every function here returns None rather than
guessing, so an unparsed request becomes "I did not catch a time for that"
instead of a reminder silently scheduled for the wrong moment.
"""

# Standard library
import re
from datetime import datetime, timedelta, timezone

# Local
from voice_concierge.scheduling.types import WEEKDAY_NAMES, Reminder, Schedule

#: Phrases that mark a request as asking for a reminder or a timer.
REMINDER_TRIGGERS: tuple[str, ...] = (
    "remind me",
    "reminder to",
    "reminder for",
    "set a timer",
    "set a reminder",
    "wake me",
    "let me know",
)

_SCHEDULE_REQUEST = re.compile(
    r"\b(?:set|start)\s+(?:(?:a|the)\s+)?(?:timer|reminder)\b",
    flags=re.IGNORECASE,
)

# Whisper can turn the short phrase "set a timer" into "it says a timer".
# Only repair that leading phrase when the rest still contains an explicit
# duration, which keeps an ordinary sentence such as "it says a timer is on"
# out of the scheduling fast path.
_MISHEARD_TIMER_REQUEST = re.compile(
    r"^(?:please\s+)?it\s+(?:says|said|sets)\s+(?=(?:a|the)\s+timer\b)",
    flags=re.IGNORECASE,
)

_UNITS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86_400,
}
_WORD_NUMBERS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty five": 45,
    "fifty": 50,
    "sixty": 60,
}

_DURATION = re.compile(
    # The article in "half an hour" sits between the count and the unit.
    r"\b(?:in|for)\s+(?P<count>\d+|[a-z]+(?:\s+five)?)\s+(?:an?\s+)?"
    r"(?P<unit>second|minute|hour|day)s?\b"
)
_EVERY_DURATION = re.compile(
    r"\bevery\s+(?P<count>\d+|[a-z]+)\s+(?P<unit>second|minute|hour)s?\b"
)
_CLOCK = re.compile(
    r"\b(?:at|by)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<meridiem>am|pm|a\.m\.|p\.m\.)?\b"
)
_EVERY_DAY = re.compile(r"\bevery\s+(?:day|morning|evening|night)\b")
_EVERY_WEEKDAY = re.compile(r"\bevery\s+(?P<day>" + "|".join(WEEKDAY_NAMES) + r")\b")
_TIMER_WORDS = re.compile(r"\b(timer|alarm)\b")

#: Words stripped from the front of the remembered text once parsed.
_LEAD_IN = re.compile(
    r"^(?:please\s+)?(?:can you\s+)?(?:remind me(?:\s+to)?"
    r"|(?:set|start)\s+(?:(?:a|the)\s+)?timer(?:\s+for)?"
    r"|(?:set|start)\s+(?:(?:a|the)\s+)?reminder(?:\s+to|\s+for)?"
    r"|reminder(?:\s+to|\s+for)?|wake me(?:\s+up)?"
    r"|let me know(?:\s+to)?)\s*",
    flags=re.IGNORECASE,
)

# A schedule may come before the subject ("remind me in ten minutes to call")
# or after it ("remind me to call in ten minutes"). The schedule parsers accept
# both arrangements, so subject extraction must do the same.
_LEADING_SCHEDULE = re.compile(
    r"^(?:"
    r"(?:in|for)\s+(?:half\s+(?:an?\s+)?|(?:\d+|[a-z]+(?:\s+five)?)\s+(?:an?\s+)?)"
    r"(?:seconds?|minutes?|hours?|days?)"
    r"|(?:at|by)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
    r"|every\s+(?:"
    r"(?:\d+|[a-z]+)\s+(?:seconds?|minutes?|hours?)"
    r"|day|morning|evening|night|" + "|".join(WEEKDAY_NAMES) + r")"
    r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)?"
    r")\s+to\s+",
    flags=re.IGNORECASE,
)


def is_reminder_request(transcript: str) -> bool:
    """True when the transcript is asking for a reminder or timer."""
    normalized = _normalize_spoken_request(transcript)
    lowered = normalized.casefold()
    return any(trigger in lowered for trigger in REMINDER_TRIGGERS) or bool(
        _SCHEDULE_REQUEST.search(normalized)
    )


_HALF = re.compile(r"\b(?:in|for)\s+half\s+(?:an?\s+)?(?P<unit>minute|hour|day)s?\b")


def parse_duration(text: str) -> int | None:
    """Return a spoken duration in seconds, or None if there is not one."""
    lowered = text.casefold()
    half = _HALF.search(lowered)
    if half is not None:
        # "half an hour" is a fraction of the unit, not a count of it.
        return _UNITS[half.group("unit")] // 2
    match = _DURATION.search(lowered)
    if match is None:
        return None
    count = _to_number(match.group("count"))
    if count is None:
        return None
    return count * _UNITS[match.group("unit")]


def parse_reminder(transcript: str, *, now: int) -> Reminder | None:
    """Parse a spoken request into a reminder, or None if no time was found.

    `now` is passed in rather than read from the clock so that "in ten minutes"
    is a pure function of its inputs and can be tested exactly.
    """
    text = _normalize_spoken_request(transcript)
    if not text:
        return None
    lowered = text.casefold()
    schedule = (
        _parse_every_duration(lowered, now)
        or _parse_every_weekday(lowered, now)
        or _parse_every_day(lowered, now)
        or _parse_clock_time(lowered, now)
        or _parse_relative(lowered, now)
    )
    if schedule is None:
        return None  # no time found: the caller asks rather than guessing
    kind = "timer" if _TIMER_WORDS.search(lowered) else "reminder"
    return Reminder(text=_subject(text), schedule=schedule, kind=kind)


def _normalize_spoken_request(transcript: str) -> str:
    """Repair a narrowly scoped speech-recognition error in timer requests."""

    text = transcript.strip()
    if _MISHEARD_TIMER_REQUEST.search(text) and parse_duration(text) is not None:
        return _MISHEARD_TIMER_REQUEST.sub("set ", text, count=1)
    return text


def _parse_relative(text: str, now: int) -> Schedule | None:
    """ "in ten minutes" and "for five minutes"."""
    seconds = parse_duration(text)
    if seconds is None:
        return None
    return Schedule(due_at=now + seconds)


def _parse_every_duration(text: str, now: int) -> Schedule | None:
    """ "every twenty minutes"."""
    match = _EVERY_DURATION.search(text)
    if match is None:
        return None
    count = _to_number(match.group("count"))
    if count is None:
        return None
    step = count * _UNITS[match.group("unit")]
    return Schedule(due_at=now + step, recurrence="interval", interval_seconds=step)


def _parse_every_day(text: str, now: int) -> Schedule | None:
    """ "every day at eight", "every morning"."""
    if _EVERY_DAY.search(text) is None:
        return None
    due = _clock_time(text, now, default_hour=_implied_hour(text))
    if due is None:
        return None
    return Schedule(due_at=due, recurrence="daily")


def _parse_every_weekday(text: str, now: int) -> Schedule | None:
    """ "every Tuesday at six"."""
    match = _EVERY_WEEKDAY.search(text)
    if match is None:
        return None
    weekday = WEEKDAY_NAMES.index(match.group("day"))
    due = _clock_time(text, now, default_hour=_implied_hour(text))
    if due is None:
        return None
    # Move to the next matching weekday at or after the parsed time.
    moment = datetime.fromtimestamp(due, tz=timezone.utc).astimezone()
    # _clock_time already returned a future time and this only moves forward,
    # so the result is always ahead of now without a further wrap-around.
    moment += timedelta(days=(weekday - moment.weekday()) % 7)
    return Schedule(
        due_at=int(moment.timestamp()), recurrence="weekly", weekday=weekday
    )


def _parse_clock_time(text: str, now: int) -> Schedule | None:
    """ "at seven", "at 19:30"."""
    due = _clock_time(text, now, default_hour=None)
    return None if due is None else Schedule(due_at=due)


def _clock_time(text: str, now: int, *, default_hour: int | None) -> int | None:
    """Resolve a clock time in the text to the next time it happens."""
    match = _CLOCK.search(text)
    if match is None:
        if default_hour is None:
            return None
        hour, minute = default_hour, 0
    else:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        hour = _apply_meridiem(hour, match.group("meridiem"), text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None  # misheard digits: refuse rather than wrap to a wrong time
    moment = datetime.fromtimestamp(now, tz=timezone.utc).astimezone()
    candidate = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    due = int(candidate.timestamp())
    if due <= now:  # that time has passed today, so mean tomorrow
        due = int((candidate + timedelta(days=1)).timestamp())
    return due


def _apply_meridiem(hour: int, meridiem: str | None, text: str) -> int:
    """Turn a spoken hour into a 24-hour hour."""
    if meridiem is not None:
        pm = meridiem.startswith("p")
        if pm and hour < 12:
            return hour + 12
        if not pm and hour == 12:
            return 0
        return hour
    # No am/pm said. "eight in the evening" still has to mean 20:00.
    if hour < 12 and re.search(r"\b(evening|night|tonight)\b", text):
        return hour + 12
    return hour


def _implied_hour(text: str) -> int | None:
    """The hour implied by "morning" or "evening" when no clock time is said."""
    if re.search(r"\bmorning\b", text):
        return 8
    if re.search(r"\b(evening|night)\b", text):
        return 20
    return None


def _to_number(token: str) -> int | None:
    """Turn a spoken or written number into an integer."""
    token = token.strip()
    if token.isdigit():
        return int(token)
    return _WORD_NUMBERS.get(token)


def _subject(text: str) -> str:
    """Strip the request wrapper, leaving what the reminder is about."""
    subject = _LEAD_IN.sub("", text.strip(), count=1)
    subject = _LEADING_SCHEDULE.sub("", subject, count=1)
    subject = re.sub(
        r"\b(?:in|for|at|by)\s+(?:\d+|[a-z]+)(?::\d{2})?\s*"
        r"(?:seconds?|minutes?|hours?|days?|am|pm|a\.m\.|p\.m\.)?\s*$",
        "",
        subject,
        flags=re.IGNORECASE,
    )
    subject = re.sub(
        r"\bevery\s+(?:day|morning|evening|night|" + "|".join(WEEKDAY_NAMES) + r")\b",
        "",
        subject,
        flags=re.IGNORECASE,
    )
    # "stretch every 20 minutes" is about stretching, not about the interval.
    subject = re.sub(
        r"\bevery\s+(?:\d+|[a-z]+)\s+(?:seconds?|minutes?|hours?)\b",
        "",
        subject,
        flags=re.IGNORECASE,
    )
    subject = subject.strip(" ,.").strip()
    return subject or text.strip()
