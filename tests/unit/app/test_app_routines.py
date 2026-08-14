# tests/unit/app/test_app_routines.py
# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.app.routines import (
    AUDIO_FAILED_PHRASE,
    PACE_CHANGED_PHRASE,
    EchoCancelledStepSpeaker,
    ListeningPlayer,
    MicCommandWaiter,
    PaceControl,
    RoutineTurnHandler,
    StepSynthesizer,
)
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.source import AudioSource
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.interfaces import CommandWaiter, StepSpeaker
from voice_concierge.routines.runner import RoutineRunner
from voice_concierge.routines.types import Routine, RoutineStep

_FRAME = b"frame"


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(8, dtype=np.int16), sample_rate=16000, channels=1
    )


def _event(command: str) -> CommandEvent:
    return CommandEvent(command=command, phrase=command)


class _Tts:
    def synthesize(self, text: str) -> CapturedAudio:
        return _audio()


class _Spotter:
    """Emits scripted events, one per frame processed."""

    def __init__(self, events: list[CommandEvent | None] | None = None) -> None:
        self._events = list(events or [])

    def process(self, frame: bytes) -> CommandEvent | None:
        return self._events.pop(0) if self._events else None


class _Player:
    """Player that feeds a fixed number of mic frames back during playback."""

    def __init__(self, *, frames: int = 1, fail: bool = False) -> None:
        self._frames = frames
        self._fail = fail
        self.calls: list[str] = []

    def play(self, audio: CapturedAudio, *, on_input_frame=None) -> None:
        if self._fail:
            raise AudioDeviceError("no device")
        self.calls.append("play")
        for _ in range(self._frames):
            if on_input_frame is not None:
                on_input_frame(_FRAME)

    def stop(self) -> None:
        self.calls.append("stop")

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")


class _Source:
    """AudioSource fake that returns frames and records open/close."""

    def __init__(self, *, fail_open: bool = False) -> None:
        self.opened = 0
        self.closed = 0
        self._fail_open = fail_open

    def open(self) -> None:
        if self._fail_open:
            raise AudioDeviceError("mic busy")
        self.opened += 1

    def read(self, num_samples: int) -> bytes:
        return _FRAME

    def close(self) -> None:
        self.closed += 1


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1  # every check advances, so a wait always terminates
        return self.now


@pytest.mark.unit
class TestStepSpeaker:
    def test_speaks_and_returns_none_when_uninterrupted(self) -> None:
        player = _Player(frames=2)
        speaker = EchoCancelledStepSpeaker(_Tts(), player, _Spotter())

        assert speaker.speak("step one") is None
        assert player.calls == ["play"]

    def test_navigation_command_cuts_the_speech_and_is_returned(self) -> None:
        player = _Player(frames=1)
        speaker = EchoCancelledStepSpeaker(_Tts(), player, _Spotter([_event("next")]))

        event = speaker.speak("step one")

        assert event is not None
        assert event.command == "next"
        assert "stop" in player.calls  # the reading was cut short

    def test_pause_holds_the_speech_without_interrupting_the_routine(self) -> None:
        player = _Player(frames=1)
        speaker = EchoCancelledStepSpeaker(_Tts(), player, _Spotter([_event("pause")]))

        assert speaker.speak("step one") is None  # routine does not move on
        assert player.calls == ["play", "pause"]

    def test_resume_is_applied_to_the_speech(self) -> None:
        player = _Player(frames=1)
        speaker = EchoCancelledStepSpeaker(_Tts(), player, _Spotter([_event("resume")]))

        assert speaker.speak("step one") is None
        assert player.calls == ["play", "resume"]

    def test_audio_failure_is_reported_as_a_stop(self) -> None:
        """A dead device must end the routine, not silently advance through it."""
        speaker = EchoCancelledStepSpeaker(_Tts(), _Player(fail=True), _Spotter())

        event = speaker.speak("step one")

        assert event is not None
        assert event.command == "stop"
        assert event.phrase == AUDIO_FAILED_PHRASE  # nobody actually said it

    def test_audio_failure_reaches_the_observer(self) -> None:
        seen: list[CommandEvent] = []
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(fail=True), _Spotter(), on_event=seen.append
        )

        speaker.speak("step one")

        assert [event.phrase for event in seen] == [AUDIO_FAILED_PHRASE]

    def test_audio_failure_ends_a_running_routine(self) -> None:
        """End to end: a dead device stops rather than reading to nobody."""
        routine = Routine(
            name="tea", steps=tuple(RoutineStep(f"step {i}") for i in range(1, 6))
        )
        adapter = RoutineCommandAdapter(StaticRoutineProvider({"tea": routine}))
        speaker = EchoCancelledStepSpeaker(_Tts(), _Player(fail=True), _Spotter())
        waiter = MicCommandWaiter(_Source(), _Spotter(), clock=_Clock())
        opening = adapter.start_routine("tea")

        RoutineRunner(adapter, speaker, waiter).run(opening)

        assert adapter.status == "stopped"  # did not walk through all 5 steps

    def test_observer_sees_recognized_commands(self) -> None:
        seen: list[CommandEvent] = []
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("next")]), on_event=seen.append
        )

        speaker.speak("step one")

        assert [event.command for event in seen] == ["next"]

    def test_satisfies_the_step_speaker_protocol(self) -> None:
        speaker = EchoCancelledStepSpeaker(_Tts(), _Player(), _Spotter())
        assert isinstance(speaker, StepSpeaker)


@pytest.mark.unit
class TestCommandWaiter:
    def test_returns_the_first_command_heard(self) -> None:
        source = _Source()
        waiter = MicCommandWaiter(
            source, _Spotter([None, _event("next")]), clock=_Clock()
        )

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "next"

    def test_returns_none_when_the_timeout_passes_quietly(self) -> None:
        waiter = MicCommandWaiter(_Source(), _Spotter(), clock=_Clock())

        assert waiter.wait(0.5) is None

    def test_always_releases_the_microphone(self) -> None:
        """The next step's playback needs the device back."""
        source = _Source()
        waiter = MicCommandWaiter(source, _Spotter([_event("stop")]), clock=_Clock())

        waiter.wait(5.0)

        assert source.opened == 1
        assert source.closed == 1

    def test_unavailable_microphone_falls_back_to_silence(self) -> None:
        waiter = MicCommandWaiter(_Source(fail_open=True), _Spotter(), clock=_Clock())

        assert waiter.wait(5.0) is None

    def test_observer_sees_recognized_commands(self) -> None:
        seen: list[CommandEvent] = []
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("back")]), clock=_Clock(), on_event=seen.append
        )

        waiter.wait(5.0)

        assert [event.command for event in seen] == ["back"]

    def test_satisfies_the_command_waiter_protocol(self) -> None:
        assert isinstance(MicCommandWaiter(_Source(), _Spotter()), CommandWaiter)


class _FailingProvider:
    def get_routine(self, request: str) -> Routine | None:
        raise RoutineError("backend down")


@pytest.mark.unit
class TestRoutineTurnHandler:
    def _handler(self, provider=None) -> RoutineTurnHandler:
        routine = Routine(name="tea", steps=(RoutineStep("boil water"),))
        adapter = RoutineCommandAdapter(
            provider or StaticRoutineProvider({"guide me through tea": routine})
        )
        speaker = EchoCancelledStepSpeaker(_Tts(), _Player(), _Spotter())
        waiter = MicCommandWaiter(_Source(), _Spotter(), clock=_Clock())
        return RoutineTurnHandler(adapter, RoutineRunner(adapter, speaker, waiter))

    def test_guidance_request_is_handled(self) -> None:
        assert self._handler().handles("guide me through making tea") is True

    def test_ordinary_request_is_left_to_the_normal_turn(self) -> None:
        assert self._handler().handles("what is the weather") is False

    def test_running_a_routine_speaks_it_to_the_end(self) -> None:
        last = self._handler().run("guide me through tea")

        assert last == "That was the last step."

    def test_unknown_routine_is_reported_not_raised(self) -> None:
        assert "don't have a routine" in self._handler().run("guide me through nothing")

    def test_backend_failure_is_reported_not_raised(self) -> None:
        """A dead reasoning backend costs one apology, not the app loop."""
        handler = self._handler(provider=_FailingProvider())

        assert handler.run("guide me through tea") == (
            "I couldn't load that routine right now."
        )


@pytest.mark.unit
class TestProtocolConformance:
    def test_fakes_match_the_declared_protocols(self) -> None:
        assert isinstance(_Tts(), StepSynthesizer)
        assert isinstance(_Player(), ListeningPlayer)
        assert isinstance(_Source(), AudioSource)


class _Pace:
    """Records pace changes, standing in for a PacedTextToSpeech."""

    def __init__(self) -> None:
        self.moves: list[str] = []

    def slower(self) -> str:
        self.moves.append("slower")
        return "Speaking more slowly."

    def faster(self) -> str:
        self.moves.append("faster")
        return "Speaking faster."


@pytest.mark.unit
class TestPacing:
    """Saying "slower" or "faster" changes the rate and re-reads the step."""

    def test_slower_changes_the_rate(self) -> None:
        pace = _Pace()
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("slower")]), pace=pace
        )

        speaker.speak("step one")

        assert pace.moves == ["slower"]

    def test_faster_changes_the_rate(self) -> None:
        pace = _Pace()
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("faster")]), pace=pace
        )

        speaker.speak("step one")

        assert pace.moves == ["faster"]

    def test_a_pacing_word_asks_for_the_step_again(self) -> None:
        """Rendered audio cannot change speed, so the step is re-read."""
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("slower")]), pace=_Pace()
        )

        event = speaker.speak("step one")

        assert event is not None
        assert event.command == "repeat"
        assert event.phrase == PACE_CHANGED_PHRASE  # nobody said "repeat"

    def test_a_pacing_word_cuts_the_current_reading(self) -> None:
        player = _Player(frames=1)
        speaker = EchoCancelledStepSpeaker(
            _Tts(), player, _Spotter([_event("slower")]), pace=_Pace()
        )

        speaker.speak("step one")

        assert "stop" in player.calls

    def test_pacing_does_not_move_through_the_routine(self) -> None:
        """ "Slower" must re-read the same step, not advance past it."""
        routine = Routine(
            name="tea", steps=(RoutineStep("step one"), RoutineStep("step two"))
        )
        adapter = RoutineCommandAdapter(StaticRoutineProvider({"tea": routine}))
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("slower")]), pace=_Pace()
        )
        opening = adapter.start_routine("tea")

        said = adapter.handle_command(speaker.speak(opening))

        assert "Step 1 of 2" in said  # still on the first step

    def test_pacing_without_a_pace_control_still_re_reads(self) -> None:
        """A speaker built without pacing must not crash on the word."""
        speaker = EchoCancelledStepSpeaker(
            _Tts(), _Player(frames=1), _Spotter([_event("slower")])
        )

        event = speaker.speak("step one")

        assert event is not None
        assert event.command == "repeat"

    def test_a_pacing_word_reaches_the_observer(self) -> None:
        seen: list[CommandEvent] = []
        speaker = EchoCancelledStepSpeaker(
            _Tts(),
            _Player(frames=1),
            _Spotter([_event("faster")]),
            pace=_Pace(),
            on_event=seen.append,
        )

        speaker.speak("step one")

        assert [event.command for event in seen] == ["faster"]  # as it was heard

    def test_the_pace_fake_matches_the_protocol(self) -> None:
        assert isinstance(_Pace(), PaceControl)


@pytest.mark.unit
class TestPacingBetweenSteps:
    """A pacing word in the quiet gap must work exactly as it does over speech."""

    def test_slower_in_the_quiet_window_changes_the_rate(self) -> None:
        pace = _Pace()
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("slower")]), clock=_Clock(), pace=pace
        )

        waiter.wait(5.0)

        assert pace.moves == ["slower"]

    def test_it_is_reported_as_a_repeat_not_as_an_unknown_command(self) -> None:
        """Passing "slower" through raw made the adapter say it did not catch it."""
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("slower")]), clock=_Clock(), pace=_Pace()
        )

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "repeat"
        assert event.phrase == PACE_CHANGED_PHRASE

    def test_the_adapter_understands_what_the_waiter_returns(self) -> None:
        """End to end: the step is re-read rather than an apology being spoken."""
        routine = Routine(
            name="tea", steps=(RoutineStep("step one"), RoutineStep("step two"))
        )
        adapter = RoutineCommandAdapter(StaticRoutineProvider({"tea": routine}))
        adapter.start_routine("tea")
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("faster")]), clock=_Clock(), pace=_Pace()
        )

        said = adapter.handle_command(waiter.wait(5.0))

        assert "Step 1 of 2" in said
        assert "didn't catch" not in said

    def test_navigation_words_still_pass_through_untouched(self) -> None:
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("next")]), clock=_Clock(), pace=_Pace()
        )

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "next"

    def test_a_waiter_without_pacing_still_re_reads(self) -> None:
        waiter = MicCommandWaiter(
            _Source(), _Spotter([_event("slower")]), clock=_Clock()
        )

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "repeat"


class _WedgedSource(_Source):
    """A mic that opens but never delivers frames, as a bad device does."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def available(self) -> int:
        return 0  # nothing ever becomes ready

    def read(self, num_samples: int) -> bytes:
        self.reads += 1
        raise AssertionError("a blocking read would hang here forever")


class _ReadySource(_Source):
    """A healthy mic that always has a full block ready."""

    def available(self) -> int:
        return 1_000_000


@pytest.mark.unit
class TestWedgedMicrophone:
    """A device that never delivers must not hold the routine, or Ctrl+C."""

    def test_a_wedged_microphone_times_out_instead_of_blocking(self) -> None:
        source = _WedgedSource()
        waiter = MicCommandWaiter(source, _Spotter(), clock=_Clock())

        assert waiter.wait(0.5) is None
        assert source.reads == 0  # never entered the blocking read
        assert source.closed == 1  # and the device was released

    def test_a_ready_microphone_is_still_read(self) -> None:
        waiter = MicCommandWaiter(
            _ReadySource(), _Spotter([_event("next")]), clock=_Clock()
        )

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "next"

    def test_a_source_without_availability_still_works(self) -> None:
        """Sources that cannot report readiness keep the previous behaviour."""
        waiter = MicCommandWaiter(_Source(), _Spotter([_event("stop")]), clock=_Clock())

        event = waiter.wait(5.0)

        assert event is not None
        assert event.command == "stop"
