# tests/unit/scheduling/test_parser.py
# Standard library
from datetime import datetime, timedelta

# Third-party
import pytest

# Local
from voice_concierge.scheduling.parser import (
    REMINDER_TRIGGERS,
    is_reminder_request,
    parse_duration,
    parse_reminder,
)

#: A fixed local reference: Monday 2026-01-05 at 10:00 local time.
NOW = int(datetime(2026, 1, 5, 10, 0).astimezone().timestamp())


def _local(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch).astimezone()


@pytest.mark.unit
class TestRecognisingRequests:
    @pytest.mark.parametrize(
        "transcript",
        [
            "remind me to take my pills",
            "set a timer for ten minutes",
            "set a reminder for tomorrow",
            "wake me at seven",
            "let me know in five minutes",
        ],
    )
    def test_reminder_requests_are_recognised(self, transcript: str) -> None:
        assert is_reminder_request(transcript) is True

    @pytest.mark.parametrize("trigger", REMINDER_TRIGGERS)
    def test_every_published_trigger_matches(self, trigger: str) -> None:
        """The exported list and the matcher cannot drift apart."""
        assert is_reminder_request(f"please {trigger} something") is True

    @pytest.mark.parametrize(
        "transcript",
        ["what is the weather", "add milk to the list", "guide me through pasta", ""],
    )
    def test_other_requests_are_not_reminders(self, transcript: str) -> None:
        assert is_reminder_request(transcript) is False


@pytest.mark.unit
class TestDurations:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("in 30 seconds", 30),
            ("for 10 minutes", 600),
            ("in two hours", 7200),
            ("in a minute", 60),
            ("for half an hour", 1800),
            ("in 3 days", 259_200),
        ],
    )
    def test_spoken_durations_are_understood(self, text: str, seconds: int) -> None:
        assert parse_duration(text) == seconds

    def test_text_without_a_duration_returns_none(self) -> None:
        assert parse_duration("remind me about the thing") is None

    def test_unknown_number_word_is_refused(self) -> None:
        """Better no reminder than one at a guessed time."""
        assert parse_duration("in umpteen minutes") is None


@pytest.mark.unit
class TestOneOffReminders:
    def test_relative_duration_schedules_from_now(self) -> None:
        reminder = parse_reminder("set a timer for 10 minutes", now=NOW)

        assert reminder is not None
        assert reminder.due_at == NOW + 600
        assert reminder.schedule.recurrence == "once"

    def test_a_timer_is_recognised_as_a_timer(self) -> None:
        reminder = parse_reminder("set a timer for 5 minutes", now=NOW)

        assert reminder is not None
        assert reminder.kind == "timer"
        assert "timer" in reminder.announcement.lower()

    def test_a_reminder_is_not_a_timer(self) -> None:
        reminder = parse_reminder("remind me to stretch in 5 minutes", now=NOW)

        assert reminder is not None
        assert reminder.kind == "reminder"
        assert reminder.text == "stretch"

    def test_clock_time_later_today(self) -> None:
        reminder = parse_reminder("remind me to call mum at 14:30", now=NOW)

        assert reminder is not None
        assert _local(reminder.due_at).hour == 14
        assert _local(reminder.due_at).minute == 30

    def test_clock_time_already_past_means_tomorrow(self) -> None:
        """At 10:00, "at 9" cannot mean nine o'clock this morning."""
        reminder = parse_reminder("remind me to call mum at 9", now=NOW)

        assert reminder is not None
        assert _local(reminder.due_at).day == _local(NOW).day + 1
        assert _local(reminder.due_at).hour == 9

    @pytest.mark.parametrize(
        ("text", "hour"),
        [
            ("remind me to eat at 8pm", 20),
            ("remind me to eat at 8 am", 8),
            ("remind me to eat at 12pm", 12),
            ("remind me to eat at 12am", 0),
            ("remind me to eat at 8 in the evening", 20),
        ],
    )
    def test_meridiem_is_applied(self, text: str, hour: int) -> None:
        reminder = parse_reminder(text, now=NOW)

        assert reminder is not None
        assert _local(reminder.due_at).hour == hour

    def test_impossible_clock_time_is_refused(self) -> None:
        """A misheard "at 99" must not wrap round to some other time."""
        assert parse_reminder("remind me at 99", now=NOW) is None


@pytest.mark.unit
class TestRecurringReminders:
    def test_every_interval_repeats(self) -> None:
        reminder = parse_reminder("remind me to stretch every 20 minutes", now=NOW)

        assert reminder is not None
        assert reminder.schedule.recurrence == "interval"
        assert reminder.schedule.interval_seconds == 1200
        assert reminder.due_at == NOW + 1200
        assert reminder.text == "stretch"  # the interval is not part of the subject

    def test_every_day_at_a_time_repeats_daily(self) -> None:
        reminder = parse_reminder("remind me to take my pills every day at 9", now=NOW)

        assert reminder is not None
        assert reminder.schedule.recurrence == "daily"
        assert _local(reminder.due_at).hour == 9
        assert reminder.text == "take my pills"

    def test_every_morning_implies_a_time(self) -> None:
        reminder = parse_reminder("remind me to stretch every morning", now=NOW)

        assert reminder is not None
        assert reminder.schedule.recurrence == "daily"
        assert _local(reminder.due_at).hour == 8

    def test_every_evening_implies_a_later_time(self) -> None:
        reminder = parse_reminder("remind me to lock up every evening", now=NOW)

        assert reminder is not None
        assert _local(reminder.due_at).hour == 20

    def test_every_weekday_repeats_weekly_on_that_day(self) -> None:
        reminder = parse_reminder(
            "remind me to put the bin out every tuesday at 7pm", now=NOW
        )

        assert reminder is not None
        assert reminder.schedule.recurrence == "weekly"
        assert reminder.schedule.weekday == 1  # Tuesday
        assert _local(reminder.due_at).weekday() == 1

    def test_weekly_without_a_time_still_needs_one(self) -> None:
        """No time of day and no implied one: refuse rather than pick midnight."""
        assert parse_reminder("remind me every wednesday", now=NOW) is None

    def test_unknown_interval_number_is_refused(self) -> None:
        assert parse_reminder("remind me every umpteen minutes", now=NOW) is None


@pytest.mark.unit
class TestRefusal:
    @pytest.mark.parametrize(
        "transcript",
        ["remind me to buy milk", "set a reminder", "remind me about the thing", "   "],
    )
    def test_a_request_without_a_time_is_refused(self, transcript: str) -> None:
        """The caller asks for a time rather than inventing one."""
        assert parse_reminder(transcript, now=NOW) is None

    def test_subject_falls_back_to_the_whole_request(self) -> None:
        """Stripping must never leave a reminder with nothing to say."""
        reminder = parse_reminder("in 5 minutes", now=NOW)

        assert reminder is not None
        assert reminder.text.strip() != ""


@pytest.mark.unit
class TestAnnouncement:
    def test_reminder_announcement_reads_naturally(self) -> None:
        reminder = parse_reminder("remind me to take my pills in 5 minutes", now=NOW)

        assert reminder is not None
        assert reminder.announcement == "Reminder: take my pills."

    def test_due_display_is_local_wall_clock(self) -> None:
        reminder = parse_reminder("remind me to eat at 14:30", now=NOW)

        assert reminder is not None
        assert "14:30" in reminder.due_display()


@pytest.mark.unit
class TestReferenceTimeIsPure:
    def test_parsing_is_a_function_of_the_supplied_now(self) -> None:
        """No hidden clock: the same words an hour later shift by an hour."""
        later = NOW + 3600

        first = parse_reminder("remind me to stretch in 10 minutes", now=NOW)
        second = parse_reminder("remind me to stretch in 10 minutes", now=later)

        assert first is not None and second is not None
        assert second.due_at - first.due_at == 3600

    def test_a_clock_time_tomorrow_is_a_day_later(self) -> None:
        tomorrow = int((_local(NOW) + timedelta(days=1)).timestamp())

        first = parse_reminder("remind me at 14:00", now=NOW)
        second = parse_reminder("remind me at 14:00", now=tomorrow)

        assert first is not None and second is not None
        assert second.due_at - first.due_at == 86_400


@pytest.mark.unit
class TestImpliedTimes:
    def test_every_day_without_any_time_is_refused(self) -> None:
        """ "every day" alone gives no hour, so asking beats picking midnight."""
        assert parse_reminder("remind me to stretch every day", now=NOW) is None
