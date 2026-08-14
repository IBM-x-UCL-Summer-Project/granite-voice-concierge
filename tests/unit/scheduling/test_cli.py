# tests/unit/scheduling/test_cli.py
# Standard library
import io
from pathlib import Path

# Third-party
import pytest

# Local
from voice_concierge.scheduling.cli import CONFIRM_WORD, main
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.store import ReminderStore

NOW = 1_800_000_000


class _Clock:
    def __init__(self) -> None:
        self.now = float(NOW)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def service(tmp_path: Path):
    clock = _Clock()
    active = ReminderService(ReminderStore(tmp_path / "r.sqlite3"), clock=clock)
    yield active, clock
    active.close()


def _run(argv, active, *, replies=None, wait=None):
    answers = list(replies or [])
    out = io.StringIO()

    def _confirm(prompt: str) -> str:
        return answers.pop(0) if answers else ""

    code = main(argv, service=active, confirm=_confirm, wait=wait, stdout=out)
    return code, out.getvalue()


@pytest.mark.unit
class TestListing:
    def test_no_command_lists_what_is_set(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to stretch in 10 minutes")

        code, out = _run([], active)

        assert code == 0
        assert "stretch" in out
        assert "1 set." in out

    def test_nothing_set_says_so(self, service) -> None:
        active, _ = service

        assert "Nothing is set." in _run([], active)[1]

    def test_a_repeating_reminder_says_that_it_repeats(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to stretch every 20 minutes")

        assert "repeats interval" in _run([], active)[1]


@pytest.mark.unit
class TestAdding:
    def test_adding_confirms_when_it_will_happen(self, service) -> None:
        active, _ = service

        code, out = _run(["add", "remind me to stretch in 10 minutes"], active)

        assert code == 0
        assert "in 10 minutes" in out
        assert len(active.upcoming()) == 1

    def test_a_request_without_a_time_is_refused(self, service) -> None:
        """Nothing is stored and the exit code says so."""
        active, _ = service

        code, out = _run(["add", "remind me to buy milk"], active)

        assert code == 1
        assert "didn't catch a time" in out
        assert active.upcoming() == ()


@pytest.mark.unit
class TestCancelling:
    def test_cancelling_removes_one(self, service) -> None:
        active, _ = service
        reminder = active.create_from_speech("remind me to stretch in 10 minutes")
        assert reminder is not None and reminder.identifier is not None

        code, out = _run(["cancel", str(reminder.identifier)], active)

        assert code == 0
        assert "Cancelled." in out
        assert active.upcoming() == ()

    def test_cancelling_something_unset_fails_loudly(self, service) -> None:
        active, _ = service

        code, out = _run(["cancel", "99"], active)

        assert code == 1
        assert "No reminder with id 99" in out


@pytest.mark.unit
class TestClearing:
    def test_typed_confirmation_clears_everything(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to stretch in 10 minutes")
        active.create_from_speech("remind me to eat in 20 minutes")

        code, out = _run(["clear"], active, replies=[CONFIRM_WORD])

        assert code == 0
        assert "Removed 2 reminders." in out
        assert active.upcoming() == ()

    def test_a_plain_yes_is_not_enough(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to stretch in 10 minutes")

        _, out = _run(["clear"], active, replies=["y"])

        assert "Left unchanged." in out
        assert len(active.upcoming()) == 1

    def test_nothing_set_needs_no_confirmation(self, service) -> None:
        active, _ = service

        assert "nothing to clear" in _run(["clear"], active)[1]

    def test_yes_flag_skips_the_prompt(self, service) -> None:
        active, _ = service
        active.create_from_speech("remind me to stretch in 10 minutes")

        assert "Removed 1 reminders." in _run(["clear", "-y"], active)[1]


@pytest.mark.unit
class TestWatching:
    def test_watch_once_delivers_what_is_already_due(self, service) -> None:
        """Reminders missed while nothing was running are announced on start."""
        active, clock = service
        active.create_from_speech("remind me to take pills in 10 minutes")
        clock.advance(600)

        code, out = _run(["watch", "--once"], active)

        assert code == 0
        assert "Reminder: take pills." in out

    def test_watch_once_with_nothing_due_says_so(self, service) -> None:
        active, _ = service

        assert "Nothing due." in _run(["watch", "--once"], active)[1]

    def test_watch_runs_until_the_wait_returns(self, service) -> None:
        active, _ = service
        waited: list[str] = []

        code, out = _run(["watch"], active, wait=lambda: waited.append("waited"))

        assert code == 0
        assert waited == ["waited"]
        assert "Watching for reminders" in out

    def test_watch_stops_cleanly_on_interrupt(self, service) -> None:
        active, _ = service

        def _interrupt() -> None:
            raise KeyboardInterrupt

        code, out = _run(["watch"], active, wait=_interrupt)

        assert code == 0
        assert "Stopped watching." in out


@pytest.mark.unit
def test_module_entry_point_is_importable() -> None:
    """`python -m voice_concierge.scheduling` must resolve to the CLI."""
    import voice_concierge.scheduling.__main__ as entry

    assert entry.main is main


@pytest.mark.unit
def test_factory_builds_a_service_over_a_given_database(tmp_path: Path) -> None:
    """The default path is only a default; callers can point it elsewhere."""
    from voice_concierge.scheduling.factory import build_reminder_service

    built = build_reminder_service(database_path=tmp_path / "custom.sqlite3")
    try:
        assert built.upcoming() == ()
        assert (tmp_path / "custom.sqlite3").exists()
    finally:
        built.close()
