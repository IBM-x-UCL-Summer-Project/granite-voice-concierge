# tests/unit/app/test_app_reminders.py
# Standard library
from pathlib import Path

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.app.reminders import (
    Player,
    ReminderTurnHandler,
    SpokenNotifier,
    Synthesizer,
)
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.scheduling.runner import Notifier
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.store import ReminderStore
from voice_concierge.scheduling.types import Reminder, Schedule

NOW = 1_800_000_000


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(8, dtype=np.int16), sample_rate=16000, channels=1
    )


class _Clock:
    def __init__(self) -> None:
        self.now = float(NOW)

    def __call__(self) -> float:
        return self.now


class _Tts:
    def __init__(self, *, failing: bool = False) -> None:
        self.spoken: list[str] = []
        self._failing = failing

    def synthesize(self, text: str) -> CapturedAudio:
        if self._failing:
            raise AudioDeviceError("no voice")
        self.spoken.append(text)
        return _audio()


class _Player:
    def __init__(self) -> None:
        self.played = 0

    def play(self, audio: CapturedAudio) -> None:
        self.played += 1


@pytest.fixture
def handler(tmp_path: Path):
    service = ReminderService(ReminderStore(tmp_path / "r.sqlite3"), clock=_Clock())
    yield ReminderTurnHandler(service), service
    service.close()


@pytest.mark.unit
class TestRecognisingRequests:
    @pytest.mark.parametrize(
        "transcript",
        [
            "remind me to stretch in ten minutes",
            "set a timer for five minutes",
            "set the timer for five minutes",
            "what reminders do i have",
            "cancel all reminders",
        ],
    )
    def test_reminder_turns_are_recognised(self, handler, transcript: str) -> None:
        active, _ = handler
        assert active.handles(transcript) is True

    @pytest.mark.parametrize(
        "transcript", ["what is the weather", "guide me through making pasta"]
    )
    def test_other_turns_are_left_alone(self, handler, transcript: str) -> None:
        active, _ = handler
        assert active.handles(transcript) is False


@pytest.mark.unit
class TestSettingByVoice:
    def test_setting_confirms_and_stores(self, handler) -> None:
        active, service = handler

        said = active.run("remind me to stretch in 10 minutes")

        assert "10 minutes" in said
        assert len(service.upcoming()) == 1

    def test_setting_the_timer_uses_the_reminder_store(self, handler) -> None:
        active, service = handler

        said = active.run("set the timer for 5 minutes")

        assert said == "Timer set for 5 minutes."
        assert len(service.upcoming()) == 1

    def test_a_request_without_a_time_asks_for_one(self, handler) -> None:
        active, service = handler

        said = active.run("remind me to buy milk")

        assert "didn't catch a time" in said
        assert service.upcoming() == ()


@pytest.mark.unit
class TestListingByVoice:
    def test_nothing_set_says_so(self, handler) -> None:
        active, _ = handler

        assert active.run("what reminders do i have") == "You have nothing set."

    def test_one_reminder_reads_naturally(self, handler) -> None:
        active, _ = handler
        active.run("remind me to stretch in 10 minutes")

        said = active.run("what reminders do i have")

        assert said.startswith("You have one: stretch,")

    def test_several_reminders_are_listed(self, handler) -> None:
        active, _ = handler
        active.run("remind me to stretch in 10 minutes")
        active.run("remind me to eat in 20 minutes")

        said = active.run("what reminders do i have")

        assert said.startswith("You have 2: ")
        assert "stretch" in said and "eat" in said


@pytest.mark.unit
class TestCancellingByVoice:
    def test_cancelling_everything_reports_the_count(self, handler) -> None:
        active, service = handler
        active.run("remind me to stretch in 10 minutes")
        active.run("remind me to eat in 20 minutes")

        assert active.run("cancel all reminders") == "Cancelled 2 reminders."
        assert service.upcoming() == ()

    def test_cancelling_one_reminder_is_singular(self, handler) -> None:
        active, _ = handler
        active.run("remind me to stretch in 10 minutes")

        assert active.run("cancel all reminders") == "Cancelled 1 reminder."

    def test_cancelling_with_nothing_set_says_so(self, handler) -> None:
        active, _ = handler

        assert active.run("cancel all reminders") == "You have nothing set."


@pytest.mark.unit
class TestSpokenNotifier:
    def test_a_due_reminder_is_spoken_and_written(self) -> None:
        tts, player, written = _Tts(), _Player(), []
        notifier = SpokenNotifier(tts, player, write=written.append)

        notifier.notify(Reminder(text="take pills", schedule=Schedule(NOW)))

        assert written == ["Reminder: take pills."]
        assert tts.spoken == ["Reminder: take pills."]
        assert player.played == 1

    def test_without_a_voice_it_still_reaches_the_user(self) -> None:
        written: list[str] = []

        SpokenNotifier(write=written.append).notify(
            Reminder(text="take pills", schedule=Schedule(NOW))
        )

        assert written == ["Reminder: take pills."]

    def test_a_broken_voice_does_not_lose_the_reminder(self) -> None:
        """Raising would make the runner retry a reminder already delivered."""
        written: list[str] = []
        notifier = SpokenNotifier(_Tts(failing=True), _Player(), write=written.append)

        notifier.notify(Reminder(text="take pills", schedule=Schedule(NOW)))

        assert written == ["Reminder: take pills."]  # printed, so not lost

    def test_it_satisfies_the_notifier_protocol(self) -> None:
        assert isinstance(SpokenNotifier(), Notifier)

    def test_fakes_match_the_declared_protocols(self) -> None:
        assert isinstance(_Tts(), Synthesizer)
        assert isinstance(_Player(), Player)
