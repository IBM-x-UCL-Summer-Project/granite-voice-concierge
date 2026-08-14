"""Wires guided routines into the live app: speech in, steps out, hands free.

This is the seam between the pure routine core and real audio. It supplies the
two things RoutineRunner needs, both of which listen while a routine is running:

* EchoCancelledStepSpeaker speaks a step through the macOS voice-processing
  player, so the microphone stays live during playback and the assistant does
  not hear itself. A playback word (pause/continue) is applied to the speech, a
  navigation word (next/back/repeat/stop) cuts the speech short and is handed
  back to the runner, and a pacing word (slower/faster) changes the rate and
  has the step read again at the new speed.
* MicCommandWaiter listens in the quiet gap after a step. Nothing is playing
  there, so a plain input stream is safe; the concurrent-stream CoreAudio -50
  only bites while output is open.

Both take their collaborators as protocols, so the whole path is testable with
fakes and no audio device.
"""

# Standard library
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.source import AudioSource
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.listener import DEFAULT_CHUNK
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.intent import is_routine_request
from voice_concierge.routines.runner import RoutineRunner

#: Words that act on the speech itself rather than moving through the routine.
PLAYBACK_HOLD = frozenset({"pause", "resume"})

#: Words that change how the step is spoken rather than which step is spoken.
PACING = frozenset({"slower", "faster"})

#: Phrase reported when a pacing word re-reads the step at the new speed. It
#: stands in for a spoken "repeat" so the routine holds its place, and is
#: distinct so a log shows the reading was restarted, not requested again.
PACE_CHANGED_PHRASE = "(pace changed)"

#: Phrase reported when playback failed rather than a command being spoken. It
#: stands in for a spoken "stop" so the runner ends the routine, and is distinct
#: so a log makes clear nobody actually said it.
AUDIO_FAILED_PHRASE = "(audio unavailable)"


@runtime_checkable
class StepSynthesizer(Protocol):
    """The slice of a text-to-speech backend this module needs."""

    def synthesize(self, text: str) -> CapturedAudio:
        """Render the text to audio."""


@runtime_checkable
class PaceControl(Protocol):
    """The slice of a paced voice needed to step the speaking rate."""

    def slower(self) -> str:
        """Speak more slowly from now on; returns what to say about it."""

    def faster(self) -> str:
        """Speak faster from now on; returns what to say about it."""


@runtime_checkable
class ListeningPlayer(Protocol):
    """A player that streams microphone frames back while it plays."""

    def play(
        self,
        audio: CapturedAudio,
        *,
        on_input_frame: Callable[[bytes], None] | None = None,
    ) -> None:
        """Play the audio, delivering captured mic frames as they arrive."""

    def stop(self) -> None:
        """Stop playback immediately."""

    def pause(self) -> None:
        """Pause playback, holding position."""

    def resume(self) -> None:
        """Resume paused playback."""


def apply_pacing(event: CommandEvent, pace: "PaceControl | None") -> CommandEvent:
    """Apply a pacing word and return the command the routine should act on.

    Rendered audio cannot change speed, so a pace change becomes a request to
    read the current step again. Shared by both listening contexts: a word
    spoken over the speech and the same word spoken into the quiet gap after it
    have to mean the same thing, or the control works only half the time.
    """
    if pace is not None:
        if event.command == "slower":
            pace.slower()
        else:
            pace.faster()
    return CommandEvent(command="repeat", phrase=PACE_CHANGED_PHRASE)


class EchoCancelledStepSpeaker:
    """Speaks a step with the mic live, returning any command that cut it off."""

    def __init__(
        self,
        text_to_speech: StepSynthesizer,
        player: ListeningPlayer,
        spotter: CommandSpotter,
        *,
        pace: PaceControl | None = None,
        on_event: Callable[[CommandEvent], None] | None = None,
    ) -> None:
        self._text_to_speech = text_to_speech
        self._player = player
        self._spotter = spotter
        self._dispatcher = CommandDispatcher(player)
        self._pace = pace
        self._on_event = on_event

    def speak(self, text: str) -> CommandEvent | None:
        """Speak the text; return a command that should drive the routine next.

        None means the step was spoken to the end (or was only paused and
        resumed), so the caller decides what happens next.
        """
        interrupt: list[CommandEvent] = []
        audio = self._text_to_speech.synthesize(text)
        try:
            self._player.play(
                audio, on_input_frame=lambda frame: self._route(frame, interrupt)
            )
        except AudioDeviceError:
            # Report the failure as a stop rather than as a completed step. A
            # completed step would auto-advance, silently reading a whole
            # routine to a user who can hear none of it, and a device-level
            # audio failure rarely clears itself mid-routine.
            event = CommandEvent(command="stop", phrase=AUDIO_FAILED_PHRASE)
            if self._on_event is not None:
                self._on_event(event)
            return event
        return interrupt[0] if interrupt else None

    def _route(self, frame: bytes, interrupt: list[CommandEvent]) -> None:
        """Send one mic frame to the spotter and act on anything it hears."""
        event = self._spotter.process(frame)
        if event is None:
            return
        if self._on_event is not None:
            self._on_event(event)
        if event.command in PLAYBACK_HOLD:
            self._dispatcher.dispatch(event)  # hold or resume the speech
            return
        if event.command in PACING:
            interrupt.append(apply_pacing(event, self._pace))
            self._player.stop()
            return
        interrupt.append(event)
        self._player.stop()


class MicCommandWaiter:
    """Listens for a command in the quiet gap between steps."""

    def __init__(
        self,
        source: AudioSource,
        spotter: CommandSpotter,
        *,
        chunk: int = DEFAULT_CHUNK,
        clock: Callable[[], float] = time.monotonic,
        pace: "PaceControl | None" = None,
        on_event: Callable[[CommandEvent], None] | None = None,
    ) -> None:
        self._source = source
        self._spotter = spotter
        self._chunk = chunk
        self._clock = clock
        self._pace = pace
        self._on_event = on_event

    def wait(self, timeout: float) -> CommandEvent | None:
        """Listen up to timeout seconds, returning the first command heard."""
        try:
            self._source.open()
        except AudioDeviceError:
            return None  # no mic: the runner falls back to auto-advancing
        try:
            deadline = self._clock() + timeout
            while self._clock() < deadline:
                event = self._spotter.process(self._source.read(self._chunk))
                if event is not None:
                    if self._on_event is not None:
                        self._on_event(event)
                    if event.command in PACING:
                        return apply_pacing(event, self._pace)
                    return event
            return None
        finally:
            self._source.close()


class RoutineTurnHandler:
    """Decides whether a turn is a routine, and runs it to completion if so."""

    def __init__(self, adapter: RoutineCommandAdapter, runner: RoutineRunner) -> None:
        self._adapter = adapter
        self._runner = runner

    def handles(self, transcript: str) -> bool:
        """True when the transcript asks to be guided through something."""
        return is_routine_request(transcript)

    def run(self, transcript: str) -> str:
        """Start the routine and run it hands-free; returns the last thing said.

        Nothing is raised for a missing routine or a dead reasoning backend:
        start_routine degrades those to a spoken apology, which the runner then
        treats as the opening line and no routine becomes active, so the app
        loop carries on either way.
        """
        return self._runner.run(self._adapter.start_routine(transcript))
