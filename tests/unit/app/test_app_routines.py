# tests/unit/app/test_app_routines.py
# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.app.routines import (
    EchoCancelledStepSpeaker,
    ListeningPlayer,
    MicCommandWaiter,
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

    def test_audio_failure_is_reported_as_no_interruption(self) -> None:
        """A dead device must not kill the routine; the session keeps its place."""
        speaker = EchoCancelledStepSpeaker(_Tts(), _Player(fail=True), _Spotter())

        assert speaker.speak("step one") is None

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
