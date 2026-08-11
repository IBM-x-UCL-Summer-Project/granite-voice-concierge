# tests/unit/routines/test_runner.py
# Third-party
import pytest

# Local
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.interfaces import CommandWaiter, StepSpeaker
from voice_concierge.routines.runner import RoutineRunner
from voice_concierge.routines.types import Routine, RoutineStep


def _routine(n: int = 3) -> Routine:
    return Routine(
        name="tea", steps=tuple(RoutineStep(f"step {i}") for i in range(1, n + 1))
    )


def _event(command: str) -> CommandEvent:
    return CommandEvent(command=command, phrase=command)


class _Speaker:
    """StepSpeaker that records what was said and replays scripted barge-ins."""

    def __init__(self, interrupts: list[CommandEvent | None] | None = None) -> None:
        self.said: list[str] = []
        self._interrupts = list(interrupts or [])

    def speak(self, text: str) -> CommandEvent | None:
        self.said.append(text)
        return self._interrupts.pop(0) if self._interrupts else None


class _Waiter:
    """CommandWaiter that replays scripted commands and records the timeouts."""

    def __init__(self, events: list[CommandEvent | None] | None = None) -> None:
        self.timeouts: list[float] = []
        self._events = list(events or [])

    def wait(self, timeout: float) -> CommandEvent | None:
        self.timeouts.append(timeout)
        return self._events.pop(0) if self._events else None


def _adapter(n: int = 3) -> RoutineCommandAdapter:
    return RoutineCommandAdapter(StaticRoutineProvider({"tea": _routine(n)}))


def _runner(
    adapter: RoutineCommandAdapter, speaker: _Speaker, waiter: _Waiter
) -> RoutineRunner:
    return RoutineRunner(
        adapter, speaker, waiter, auto_advance_delay=5.0, idle_timeout=99.0
    )


@pytest.mark.unit
class TestAutoAdvance:
    """Silence carries the routine forward on its own."""

    def test_silence_walks_through_every_step_to_the_end(self) -> None:
        adapter = _adapter(3)
        speaker, waiter = _Speaker(), _Waiter()  # never interrupts, never hears
        opening = adapter.start_routine("tea")

        _runner(adapter, speaker, waiter).run(opening)

        assert "Step 1 of 3" in speaker.said[0]
        assert "Step 2 of 3" in speaker.said[1]
        assert "Step 3 of 3" in speaker.said[2]
        assert speaker.said[-1] == "That was the last step."
        assert adapter.status == "finished"

    def test_running_step_waits_only_the_auto_advance_delay(self) -> None:
        adapter = _adapter(2)
        speaker, waiter = _Speaker(), _Waiter()

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert waiter.timeouts[0] == 5.0  # not the long idle timeout


@pytest.mark.unit
class TestSpokenCommands:
    """Commands steer the routine from either listening context."""

    def test_command_heard_after_a_step_is_applied(self) -> None:
        adapter = _adapter(3)
        speaker = _Speaker()
        waiter = _Waiter([_event("repeat"), _event("stop")])

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert "Step 1 of 3" in speaker.said[0]
        assert "Step 1 of 3" in speaker.said[1]  # repeated, did not advance
        assert speaker.said[-1] == "Routine stopped."

    def test_command_barged_in_over_a_step_is_applied(self) -> None:
        adapter = _adapter(3)
        speaker = _Speaker([_event("stop")])  # interrupts the very first step
        waiter = _Waiter()

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert speaker.said[-1] == "Routine stopped."
        assert waiter.timeouts == []  # never reached the quiet window

    def test_stop_ends_the_run_and_speaks_the_closing_line(self) -> None:
        adapter = _adapter(3)
        speaker = _Speaker()
        waiter = _Waiter([_event("stop")])

        last = _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert last == "Routine stopped."
        assert adapter.status == "stopped"


@pytest.mark.unit
class TestPause:
    """A paused routine holds instead of advancing."""

    def test_paused_routine_does_not_auto_advance(self) -> None:
        adapter = _adapter(3)
        speaker = _Speaker()
        waiter = _Waiter([_event("pause")])  # then silence

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert adapter.status == "paused"
        # step 1, then the paused acknowledgement; never reached step 2
        assert not any("Step 2 of 3" in said for said in speaker.said)

    def test_paused_routine_waits_the_long_idle_timeout(self) -> None:
        adapter = _adapter(3)
        speaker = _Speaker()
        waiter = _Waiter([_event("pause")])

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert waiter.timeouts == [5.0, 99.0]  # short while running, long while paused

    def test_continue_resumes_and_the_routine_carries_on(self) -> None:
        adapter = _adapter(2)
        speaker = _Speaker()
        waiter = _Waiter([_event("pause"), _event("resume")])

        _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert adapter.status == "finished"
        assert speaker.said[-1] == "That was the last step."


@pytest.mark.unit
class TestConformance:
    def test_fakes_satisfy_the_runner_protocols(self) -> None:
        assert isinstance(_Speaker(), StepSpeaker)
        assert isinstance(_Waiter(), CommandWaiter)

    def test_uses_documented_defaults_when_not_configured(self) -> None:
        adapter = _adapter(1)
        speaker, waiter = _Speaker(), _Waiter()

        RoutineRunner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert waiter.timeouts[0] == 6.0  # DEFAULT_AUTO_ADVANCE_DELAY


@pytest.mark.unit
class TestNoActiveRoutine:
    """A run that never started must not hold the microphone open."""

    def test_unknown_routine_returns_without_listening(self) -> None:
        adapter = RoutineCommandAdapter(StaticRoutineProvider({}))
        speaker, waiter = _Speaker(), _Waiter()
        opening = adapter.start_routine("something we do not have")

        last = _runner(adapter, speaker, waiter).run(opening)

        assert last == "I don't have a routine for that."
        assert speaker.said == [last]  # the apology was spoken once
        assert waiter.timeouts == []  # and nothing waited for a command

    def test_backend_failure_returns_without_listening(self) -> None:
        class _Failing:
            def get_routine(self, request: str):
                raise RoutineError("backend down")

        adapter = RoutineCommandAdapter(_Failing())
        speaker, waiter = _Speaker(), _Waiter()

        last = _runner(adapter, speaker, waiter).run(adapter.start_routine("tea"))

        assert last == "I couldn't load that routine right now."
        assert waiter.timeouts == []
