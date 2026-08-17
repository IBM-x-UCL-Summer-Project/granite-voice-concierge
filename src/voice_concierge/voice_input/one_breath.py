"""Wake word and utterance capture over a single, never-closed audio stream.

The original pipeline ran the two stages as separate components, each owning
its own microphone: the wake word detector closed the device so the voice
activity detector could open it. That handoff costs whatever is spoken during
it, which is exactly the words following the wake word. It forces the two-beat
interaction of saying "Hey Jarvis", waiting, then speaking.

Here both stages read from one stream that is opened once, and the audio before
the wake word fired is kept in a rolling buffer and put in front of the
utterance. The result is that a whole sentence spoken in one breath survives.

The recognisers are injected as chunk-level protocols rather than whole
components. openWakeWord and Silero both load native models in their
constructors, which makes anything holding them directly untestable; reducing
each to "given these bytes, what do you say" puts the whole control flow of
this module under deterministic test with no device and no model.
"""

# Standard library
import time
from collections.abc import Callable
from typing import Final, Literal, Protocol, runtime_checkable

# Third-party
import numpy as np

# Local
from voice_concierge.audio import AudioSource, CapturedAudio
from voice_concierge.voice_input.preroll import (
    DEFAULT_PREROLL_SECONDS,
    DEFAULT_RATE,
    RollingAudioBuffer,
)

#: Samples per read. Matches openWakeWord's expected chunk, about 80ms.
DEFAULT_CHUNK: Final[int] = 1280

#: Seconds to keep waiting for the wake word before giving up on this attempt.
DEFAULT_WAKE_TIMEOUT_S: Final[float] = 30.0

#: Seconds after waking to wait for the speaker to finish before cutting them
#: off. Generous: a routine request can be a long sentence.
DEFAULT_UTTERANCE_TIMEOUT_S: Final[float] = 15.0

#: What a speech gate can say about a chunk.
SpeechVerdict = Literal["start", "end"]


@runtime_checkable
class WakeWordSpotter(Protocol):
    """Decides whether the wake word has just been said."""

    def spotted(self, chunk: bytes) -> bool:
        """True when this chunk completes the wake word."""

    def reset(self) -> None:
        """Forget accumulated audio, so the next attempt starts clean."""


@runtime_checkable
class SpeechGate(Protocol):
    """Reports the edges of speech within a stream of chunks."""

    def classify(self, chunk: bytes) -> SpeechVerdict | None:
        """Return "start" or "end" at a boundary, otherwise None."""

    def reset(self) -> None:
        """Forget accumulated audio, so the next utterance starts clean."""


class OneBreathCapturer:
    """Captures an utterance that may begin in the same breath as the wake word.

    Satisfies the same role as the wake-word-then-VAD pair it replaces, but
    holds the stream open across both stages so nothing is dropped between
    them.
    """

    def __init__(
        self,
        *,
        audio_source: AudioSource,
        spotter: WakeWordSpotter,
        speech_gate: SpeechGate,
        preroll: RollingAudioBuffer | None = None,
        chunk: int = DEFAULT_CHUNK,
        rate: int = DEFAULT_RATE,
        channels: int = 1,
        wake_timeout_s: float = DEFAULT_WAKE_TIMEOUT_S,
        utterance_timeout_s: float = DEFAULT_UTTERANCE_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        announce: Callable[[str], None] = print,
    ) -> None:
        self._source = audio_source
        self._spotter = spotter
        self._gate = speech_gate
        self._preroll = preroll or RollingAudioBuffer(
            max_seconds=DEFAULT_PREROLL_SECONDS, rate=rate
        )
        self._chunk = chunk
        self._rate = rate
        self._channels = channels
        self._wake_timeout_s = wake_timeout_s
        self._utterance_timeout_s = utterance_timeout_s
        self._clock = clock
        self._announce = announce

    def capture_utterance(
        self, on_utterance_captured: Callable[[CapturedAudio], None]
    ) -> bool:
        """Wait for the wake word, capture what follows, and deliver it.

        Returns True when an utterance was delivered, False when the attempt
        timed out. The caller loops on this, so a timeout is an ordinary
        outcome rather than an error.
        """
        self._spotter.reset()
        self._gate.reset()
        self._preroll.clear()

        if not self._await_wake_word():
            return False

        utterance = self._collect_utterance()
        if utterance is None:
            return False

        on_utterance_captured(
            CapturedAudio(
                samples=np.frombuffer(utterance, dtype=np.int16),
                sample_rate=self._rate,
                channels=self._channels,
            )
        )
        return True

    def _await_wake_word(self) -> bool:
        """Read until the wake word is spotted, feeding the rolling buffer."""
        deadline = self._clock() + self._wake_timeout_s

        while self._clock() < deadline:
            chunk = self._source.read(self._chunk)
            # Buffered before the check, so the chunk that completes the wake
            # word is itself retained. The tail of "Hey Jarvis" and the start of
            # the request often share a chunk.
            self._preroll.extend(chunk)
            if self._spotter.spotted(chunk):
                self._announce("Wake word detected — still listening...")
                return True

        self._announce("No wake word heard.")
        return False

    def _collect_utterance(self) -> bytes | None:
        """Gather speech until it ends, starting from the retained audio."""
        collected = bytearray(self._preroll.snapshot())
        self._preroll.clear()
        # The retained audio already holds the speaker mid-sentence whenever
        # they ran the wake word into their request, so treat speech as under
        # way rather than waiting for an onset that has already happened.
        speaking = bool(collected)
        deadline = self._clock() + self._utterance_timeout_s

        while self._clock() < deadline:
            chunk = self._source.read(self._chunk)
            collected.extend(chunk)
            verdict = self._gate.classify(chunk)

            if verdict == "start":
                speaking = True
            elif verdict == "end" and speaking:
                return bytes(collected)

        if speaking:
            # Ran long rather than never started. Hand over what there is;
            # a clipped request still beats silently dropping the turn.
            self._announce("Utterance ran long — using what was captured.")
            return bytes(collected)

        self._announce("Nothing said after the wake word.")
        return None


def strip_wake_phrase(transcript: str, phrases: tuple[str, ...]) -> str:
    """Remove a leading wake phrase from a transcript.

    Retaining the pre-roll means the wake word is now inside the audio, so the
    recogniser transcribes it. Substring matchers such as the routine and
    reminder triggers are unbothered, but the context-mode matcher is anchored
    to the whole utterance and would silently stop matching "switch to driving
    mode" once it arrived as "hey jarvis, switch to driving mode".
    """
    cleaned = transcript.strip()
    lowered = cleaned.casefold()

    for phrase in phrases:
        candidate = phrase.casefold()
        if not lowered.startswith(candidate):
            continue
        remainder = cleaned[len(phrase) :]
        # Drop the punctuation and space the recogniser puts between the wake
        # phrase and the request.
        return remainder.lstrip(" ,.!?;:").strip()

    return cleaned
