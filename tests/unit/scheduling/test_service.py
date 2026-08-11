# tests/unit/scheduling/test_service.py
# Standard library
from pathlib import Path

# Third-party
import pytest

# Local
from voice_concierge.scheduling.errors import SchedulingError
from voice_concierge.scheduling.runner import (
    Notifier,
    PrintNotifier,
    ReminderRunner,
    check_once,
    wait_for,
)
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.store import ReminderStore
from voice_concierge.scheduling.types import Reminder, Schedule

NOW = 1_800_000_000


class _Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: int = NOW) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingNotifier:
    def __init__(self, *, failing: bool = False) -> None:
        self.announced: list[str] = []
        self._failing = failing

    def notify(self, reminder: Reminder) -> None:
        if self._failing:
            raise RuntimeError("speaker unplugged")
        self.announced.append(reminder.text)


@pytest.fixture
def service(tmp_path: Path):
    clock = _Clock()
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    active = ReminderService(store, clock=clock)
    yield active, clock
    active.close()


@pytest.mark.unit
class TestStorage:
    def test_a_reminder_survives_a_restart(self, tmp_path: Path) -> None:
        """The point of storing: a reminder outlives the process that set it."""
        path = tmp_path / "reminders.sqlite3"
        first = ReminderService(ReminderStore(path), clock=_Clock())
        first.create_from_speech("remind me to take my pills in 10 minutes")
        first.close()

        second = ReminderService(ReminderStore(path), clock=_Clock())
        pending = second.upcoming()
        second.close()

        assert [reminder.text for reminder in pending] == ["take my pills"]

    def test_a_stored_reminder_keeps_its_recurrence(self, tmp_path: Path) -> None:
        path = tmp_path / "reminders.sqlite3"
        first = ReminderService(ReminderStore(path), clock=_Clock())
        first.create_from_speech("remind me to stretch every 20 minutes")
        first.close()

        second = ReminderService(ReminderStore(path), clock=_Clock())
        stored = second.upcoming()[0]
        second.close()

        assert stored.schedule.recurrence == "interval"
        assert stored.schedule.interval_seconds == 1200

    def test_storing_gives_the_reminder_an_identifier(self, service) -> None:
        active, _ = service

        reminder = active.create_from_speech("remind me to eat in 5 minutes")

        assert reminder is not None
        assert reminder.identifier is not None

    def test_an_unopenable_database_reports_clearly(self, tmp_path: Path) -> None:
        target = tmp_path / "occupied"
        target.mkdir()  # a directory cannot be opened as a database file

        with pytest.raises(SchedulingError, match="Could not open"):
            ReminderStore(target)

    def test_listing_all_includes_delivered_reminders(self, tmp_path: Path) -> None:
        store = ReminderStore(tmp_path / "r.sqlite3")
        stored = store.add(Reminder(text="eat", schedule=Schedule(NOW)), now=NOW)
        assert stored.identifier is not None
        store.complete(stored.identifier)

        assert store.list_pending() == ()
        assert len(store.list_all()) == 1
        store.close()

    def test_getting_a_reminder_by_id(self, tmp_path: Path) -> None:
        store = ReminderStore(tmp_path / "r.sqlite3")
        stored = store.add(Reminder(text="eat", schedule=Schedule(NOW)), now=NOW)
        assert stored.identifier is not None

        assert store.get(stored.identifier) is not None
        assert store.get(999) is None
        store.close()


@pytest.mark.unit
class TestCreating:
    def test_a_request_without_a_time_is_not_stored(self, service) -> None:
        active, _ = service

        assert active.create_from_speech("remind me to buy milk") is None
        assert active.upcoming() == ()

    def test_confirmation_states_when_it_will_happen(self, service) -> None:
        """A misheard time should be caught when set, not when it fails to come."""
        active, _ = service
        reminder = active.create_from_speech("remind me to stretch in 10 minutes")

        assert (
            active.confirmation(reminder) == "I'll remind you to stretch in 10 minutes."
        )

    def test_confirmation_for_a_timer_reads_as_a_timer(self, service) -> None:
        active, _ = service
        reminder = active.create_from_speech("set a timer for 5 minutes")

        assert active.confirmation(reminder) == "Timer set for 5 minutes."

    def test_confirmation_for_an_interval_says_how_often(self, service) -> None:
        active, _ = service
        reminder = active.create_from_speech("remind me to stretch every 20 minutes")

        assert active.confirmation(reminder) == (
            "I'll remind you to stretch every 20 minutes."
        )

    def test_confirmation_for_a_daily_reminder_names_the_recurrence(
        self, service
    ) -> None:
        active, _ = service
        reminder = active.create_from_speech("remind me to take pills every morning")

        assert "daily" in active.confirmation(reminder)

    def test_confirmation_when_nothing_was_understood_asks_for_a_time(
        self, service
    ) -> None:
        active, _ = service

        assert "didn't catch a time" in active.confirmation(None)


@pytest.mark.unit
class TestDue:
    def test_nothing_is_due_before_its_time(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to eat in 10 minutes")

        assert active.due() == ()

    def test_a_reminder_is_due_once_its_time_arrives(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")

        clock.advance(600)

        assert [reminder.text for reminder in active.due()] == ["eat"]

    def test_a_reminder_missed_while_off_is_still_due(self, service) -> None:
        """A missed medication reminder is announced late, never skipped."""
        active, clock = service
        active.create_from_speech("remind me to take pills in 10 minutes")

        clock.advance(3 * 86_400)  # the assistant was off for three days

        assert [reminder.text for reminder in active.due()] == ["take pills"]


@pytest.mark.unit
class TestAcknowledging:
    def test_a_one_off_reminder_does_not_come_back(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")
        clock.advance(600)

        active.acknowledge(active.due()[0])

        assert active.due() == ()
        assert active.upcoming() == ()

    def test_a_repeating_reminder_is_scheduled_again(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to stretch every 20 minutes")
        clock.advance(1200)

        active.acknowledge(active.due()[0])

        assert active.due() == ()  # not due right now
        assert len(active.upcoming()) == 1  # but still set

    def test_a_repeat_missed_for_a_week_fires_once_not_hundreds(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to stretch every 20 minutes")
        clock.advance(7 * 86_400)

        due = active.due()
        active.acknowledge(due[0])

        assert len(due) == 1
        assert active.due() == ()  # caught up in one step, not hundreds

    def test_an_unsaved_reminder_cannot_be_acknowledged(self, service) -> None:
        active, _ = service

        with pytest.raises(SchedulingError, match="unsaved"):
            active.acknowledge(Reminder(text="eat", schedule=Schedule(NOW)))


@pytest.mark.unit
class TestCancelling:
    def test_cancelling_removes_a_reminder(self, service) -> None:
        active, _ = service
        reminder = active.create_from_speech("remind me to eat in 10 minutes")
        assert reminder is not None and reminder.identifier is not None

        active.cancel(reminder.identifier)

        assert active.upcoming() == ()

    def test_cancelling_something_unset_is_reported(self, service) -> None:
        active, _ = service

        with pytest.raises(SchedulingError, match="No reminder with id 99"):
            active.cancel(99)

    def test_cancel_all_reports_how_many_went(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to eat in 10 minutes")
        active.create_from_speech("remind me to stretch in 20 minutes")

        assert active.cancel_all() == 2
        assert active.upcoming() == ()


@pytest.mark.unit
class TestDelivery:
    def test_due_reminders_are_announced_and_acknowledged(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")
        clock.advance(600)
        notifier = _RecordingNotifier()

        delivered = check_once(active, notifier)

        assert notifier.announced == ["eat"]
        assert [reminder.text for reminder in delivered] == ["eat"]
        assert active.due() == ()

    def test_nothing_due_announces_nothing(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to eat in 10 minutes")
        notifier = _RecordingNotifier()

        assert check_once(active, notifier) == ()
        assert notifier.announced == []

    def test_a_failed_announcement_leaves_the_reminder_due(self, service) -> None:
        """A broken speaker delays a reminder; it must not swallow it."""
        active, clock = service
        active.create_from_speech("remind me to take pills in 10 minutes")
        clock.advance(600)

        delivered = check_once(active, _RecordingNotifier(failing=True))

        assert delivered == ()
        assert len(active.due()) == 1  # still waiting to be delivered

    def test_one_broken_announcement_does_not_block_the_others(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")
        active.create_from_speech("remind me to stretch in 10 minutes")
        clock.advance(600)

        class _FailsFirst:
            def __init__(self) -> None:
                self.announced: list[str] = []

            def notify(self, reminder: Reminder) -> None:
                if not self.announced and reminder.text == "eat":
                    self.announced.append("attempted")
                    raise RuntimeError("boom")
                self.announced.append(reminder.text)

        notifier = _FailsFirst()
        delivered = check_once(active, notifier)

        assert "stretch" in notifier.announced
        assert [reminder.text for reminder in delivered] == ["stretch"]

    def test_print_notifier_writes_the_announcement(self) -> None:
        written: list[str] = []
        PrintNotifier(written.append).notify(
            Reminder(text="eat", schedule=Schedule(NOW))
        )

        assert written == ["Reminder: eat."]

    def test_notifiers_satisfy_the_protocol(self) -> None:
        assert isinstance(PrintNotifier(), Notifier)
        assert isinstance(_RecordingNotifier(), Notifier)


@pytest.mark.unit
class TestRunner:
    def test_check_now_delivers_without_the_timer(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")
        clock.advance(600)
        notifier = _RecordingNotifier()

        delivered = ReminderRunner(active, notifier).check_now()

        assert [reminder.text for reminder in delivered] == ["eat"]

    def test_the_background_thread_delivers_a_due_reminder(self, service) -> None:
        active, clock = service
        active.create_from_speech("remind me to eat in 10 minutes")
        clock.advance(600)
        notifier = _RecordingNotifier()

        with ReminderRunner(active, notifier, poll_seconds=0.01) as runner:
            assert runner.running is True
            assert wait_for(lambda: notifier.announced == ["eat"]) is True

    def test_stopping_ends_the_thread(self, service) -> None:
        active, _ = service
        runner = ReminderRunner(active, _RecordingNotifier(), poll_seconds=0.01)

        runner.start()
        runner.stop()

        assert runner.running is False

    def test_starting_twice_is_harmless(self, service) -> None:
        active, _ = service
        runner = ReminderRunner(active, _RecordingNotifier(), poll_seconds=0.01)

        runner.start()
        runner.start()
        try:
            assert runner.running is True
        finally:
            runner.stop()

    def test_stopping_when_never_started_is_safe(self, service) -> None:
        active, _ = service

        ReminderRunner(active, _RecordingNotifier()).stop()  # must not raise

    def test_wait_for_gives_up_on_a_condition_that_never_holds(self) -> None:
        assert wait_for(lambda: False, timeout=0.02) is False


@pytest.mark.unit
class TestThreadSafety:
    def test_the_store_is_usable_from_another_thread(self, tmp_path: Path) -> None:
        """The background runner polls from its own thread, so this must work."""
        import threading

        store = ReminderStore(tmp_path / "r.sqlite3")
        store.add(Reminder(text="eat", schedule=Schedule(NOW)), now=NOW)
        seen: list[int] = []
        errors: list[str] = []

        def _read() -> None:
            try:
                seen.append(len(store.list_pending()))
            except Exception as exc:  # a cross-thread failure would land here
                errors.append(repr(exc))

        thread = threading.Thread(target=_read)
        thread.start()
        thread.join()
        store.close()

        assert errors == []
        assert seen == [1]

    def test_a_relative_database_path_needs_no_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare filename has no parent directory to create."""
        monkeypatch.chdir(tmp_path)
        store = ReminderStore("reminders.sqlite3")

        assert store.list_pending() == ()
        store.close()


@pytest.mark.unit
def test_wait_for_checks_once_even_with_no_time_left() -> None:
    """A zero timeout still gets one look, rather than reporting a false miss."""
    calls: list[int] = []

    def _condition() -> bool:
        calls.append(1)
        return True

    assert wait_for(_condition, timeout=0.0) is True
    assert calls == [1]
