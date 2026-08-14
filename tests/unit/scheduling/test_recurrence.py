# tests/unit/scheduling/test_recurrence.py
# Standard library
from datetime import datetime, timedelta

# Third-party
import pytest

# Local
from voice_concierge.scheduling.recurrence import (
    advance,
    describe_delay,
    next_occurrence,
    seconds_until,
)
from voice_concierge.scheduling.types import Reminder, Schedule

#: Monday 2026-01-05 at 09:00 local time.
NOW = int(datetime(2026, 1, 5, 9, 0).astimezone().timestamp())
HOUR = 3600
DAY = 86_400


def _local(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch).astimezone()


@pytest.mark.unit
class TestOneOff:
    def test_a_one_off_reminder_never_fires_again(self) -> None:
        schedule = Schedule(due_at=NOW)

        assert next_occurrence(schedule, NOW) is None
        assert advance(schedule, NOW) is None

    def test_a_one_off_schedule_does_not_claim_to_repeat(self) -> None:
        assert Schedule(due_at=NOW).repeats is False


@pytest.mark.unit
class TestInterval:
    def test_advances_by_one_interval(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="interval", interval_seconds=600)

        assert next_occurrence(schedule, NOW) == NOW + 600

    def test_a_long_gap_skips_to_the_next_future_slot(self) -> None:
        """A reminder missed for a week must not fire hundreds of times."""
        schedule = Schedule(due_at=NOW, recurrence="interval", interval_seconds=600)

        upcoming = next_occurrence(schedule, NOW + 7 * DAY)

        assert upcoming is not None
        assert upcoming > NOW + 7 * DAY
        assert upcoming <= NOW + 7 * DAY + 600

    def test_a_due_time_still_ahead_is_kept(self) -> None:
        schedule = Schedule(
            due_at=NOW + 600, recurrence="interval", interval_seconds=600
        )

        assert next_occurrence(schedule, NOW) == NOW + 600

    def test_advance_preserves_the_recurrence(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="interval", interval_seconds=600)

        moved = advance(schedule, NOW)

        assert moved is not None
        assert moved.recurrence == "interval"
        assert moved.interval_seconds == 600
        assert moved.due_at == NOW + 600


@pytest.mark.unit
class TestDaily:
    def test_keeps_the_local_time_of_day(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="daily")

        upcoming = next_occurrence(schedule, NOW)

        assert upcoming is not None
        assert _local(upcoming).hour == 9
        assert _local(upcoming).date() == _local(NOW).date() + timedelta(days=1)

    def test_a_time_still_ahead_today_stays_today(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="daily")
        earlier = NOW - 2 * HOUR  # 07:00, so 09:00 today is still to come

        upcoming = next_occurrence(schedule, earlier)

        assert upcoming is not None
        assert _local(upcoming).date() == _local(NOW).date()

    def test_a_missed_day_moves_to_the_next_one_not_many(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="daily")

        upcoming = next_occurrence(schedule, NOW + 3 * DAY)

        assert upcoming is not None
        assert upcoming <= NOW + 4 * DAY
        assert _local(upcoming).hour == 9


@pytest.mark.unit
class TestWeekly:
    def test_fires_on_the_named_weekday(self) -> None:
        # Due Monday, repeating on Wednesday (weekday 2).
        schedule = Schedule(due_at=NOW, recurrence="weekly", weekday=2)

        upcoming = next_occurrence(schedule, NOW)

        assert upcoming is not None
        assert _local(upcoming).weekday() == 2
        assert _local(upcoming).hour == 9

    def test_the_same_weekday_later_today_stays_today(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="weekly", weekday=0)  # Monday
        earlier = NOW - 2 * HOUR

        upcoming = next_occurrence(schedule, earlier)

        assert upcoming is not None
        assert _local(upcoming).date() == _local(NOW).date()

    def test_the_same_weekday_already_past_moves_a_week(self) -> None:
        schedule = Schedule(due_at=NOW, recurrence="weekly", weekday=0)

        upcoming = next_occurrence(schedule, NOW)

        assert upcoming is not None
        assert _local(upcoming).weekday() == 0
        assert upcoming == NOW + 7 * DAY


@pytest.mark.unit
class TestValidation:
    def test_an_interval_schedule_needs_an_interval(self) -> None:
        with pytest.raises(ValueError, match="interval_seconds"):
            Schedule(due_at=NOW, recurrence="interval")

    def test_a_weekly_schedule_needs_a_weekday(self) -> None:
        with pytest.raises(ValueError, match="weekday"):
            Schedule(due_at=NOW, recurrence="weekly")

    def test_a_zero_interval_is_refused(self) -> None:
        """A zero interval would fire forever without advancing."""
        with pytest.raises(ValueError, match="positive"):
            Schedule(due_at=NOW, recurrence="interval", interval_seconds=0)

    def test_an_impossible_weekday_is_refused(self) -> None:
        with pytest.raises(ValueError, match="0 .Monday. to 6"):
            Schedule(due_at=NOW, recurrence="weekly", weekday=9)

    def test_a_reminder_needs_something_to_say(self) -> None:
        with pytest.raises(ValueError, match="something to say"):
            Reminder(text="   ", schedule=Schedule(due_at=NOW))


@pytest.mark.unit
class TestHelpers:
    def test_seconds_until_counts_down(self) -> None:
        assert seconds_until(NOW + 90, NOW) == 90

    def test_seconds_until_never_goes_negative(self) -> None:
        assert seconds_until(NOW - 90, NOW) == 0

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (1, "1 second"),
            (45, "45 seconds"),
            (60, "1 minute"),
            (600, "10 minutes"),
            (3600, "1 hour"),
            (7200, "2 hours"),
            (86_400, "1 day"),
            (172_800, "2 days"),
        ],
    )
    def test_delays_are_described_the_way_people_say_them(
        self, seconds: int, expected: str
    ) -> None:
        assert describe_delay(seconds) == expected


@pytest.mark.unit
class TestReminderDisplay:
    def test_a_timer_announcement_differs_from_a_reminder(self) -> None:
        timer = Reminder(text="10 minutes", schedule=Schedule(NOW), kind="timer")
        reminder = Reminder(text="take pills", schedule=Schedule(NOW))

        assert timer.announcement == "Your timer for 10 minutes is up."
        assert reminder.announcement == "Reminder: take pills."

    def test_due_display_shows_local_wall_clock(self) -> None:
        reminder = Reminder(text="eat", schedule=Schedule(due_at=NOW))

        assert "09:00" in reminder.due_display()

    def test_due_at_reads_through_to_the_schedule(self) -> None:
        reminder = Reminder(text="eat", schedule=Schedule(due_at=NOW + 5))

        assert reminder.due_at == NOW + 5


@pytest.mark.unit
class TestEdgeCases:
    def test_a_weekly_reminder_named_for_today_but_past_moves_a_week(self) -> None:
        """Said on Monday evening, "every Monday at 9" means next Monday."""
        # Parsed via the parser so the weekly wrap-around path is exercised.
        from voice_concierge.scheduling.parser import parse_reminder

        monday_evening = int(datetime(2026, 1, 5, 22, 0).astimezone().timestamp())
        reminder = parse_reminder(
            "remind me to stretch every monday at 9am", now=monday_evening
        )

        assert reminder is not None
        assert _local(reminder.due_at).weekday() == 0
        assert reminder.due_at > monday_evening

    def test_due_display_accepts_an_explicit_timezone(self) -> None:
        from datetime import timezone as tz

        reminder = Reminder(text="eat", schedule=Schedule(due_at=NOW))

        shown = reminder.due_display(local_timezone=tz.utc)

        assert "at" in shown
