# tests/unit/voice_input/test_one_breath.py
# Standard library
from collections.abc import Sequence

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.one_breath import (
    OneBreathCapturer,
    SpeechGate,
    SpeechVerdict,
    WakeWordSpotter,
    strip_wake_phrase,
)
from voice_concierge.voice_input.preroll import RollingAudioBuffer

SAMPLE = b"\x01\x00"  # one quiet 16-bit sample, stands in for a chunk


class ScriptedSource:
    """Serves a fixed list of chunks, then silence forever."""

    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = list(chunks)
        self.reads = 0
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def read(self, num_samples: int) -> bytes:
        self.reads += 1
        if self._chunks:
            return self._chunks.pop(0)
        return SAMPLE

    def close(self) -> None:
        self.closed += 1


class ScriptedSpotter:
    """Fires the wake word on a chosen read."""

    def __init__(self, fire_on_read: int | None = 1) -> None:
        self._fire_on_read = fire_on_read
        self._reads = 0
        self.resets = 0

    def spotted(self, chunk: bytes) -> bool:
        self._reads += 1
        return self._reads == self._fire_on_read

    def reset(self) -> None:
        self.resets += 1


class ScriptedGate:
    """Returns a fixed sequence of verdicts, then None forever."""

    def __init__(self, verdicts: Sequence[SpeechVerdict | None] = ()) -> None:
        self._verdicts = list(verdicts)
        self.resets = 0

    def classify(self, chunk: bytes) -> SpeechVerdict | None:
        if self._verdicts:
            return self._verdicts.pop(0)
        return None

    def reset(self) -> None:
        self.resets += 1


class ManualClock:
    """A clock that only advances when the test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _capturer(
    *,
    source: ScriptedSource,
    spotter: ScriptedSpotter | None = None,
    gate: ScriptedGate | None = None,
    preroll: RollingAudioBuffer | None = None,
    clock: ManualClock | None = None,
    **overrides,
) -> OneBreathCapturer:
    return OneBreathCapturer(
        audio_source=source,
        spotter=spotter or ScriptedSpotter(),
        speech_gate=gate or ScriptedGate(["end"]),
        preroll=preroll or RollingAudioBuffer(max_seconds=1.0, rate=8, sample_width=2),
        chunk=1,
        rate=8,
        clock=clock or (lambda: 0.0),
        announce=lambda _message: None,
        **overrides,
    )


def _captured(capturer: OneBreathCapturer) -> tuple[bool, list[CapturedAudio]]:
    received: list[CapturedAudio] = []
    delivered = capturer.capture_utterance(received.append)
    return delivered, received


@pytest.mark.unit
class TestConformance:
    def test_fakes_satisfy_the_protocols(self) -> None:
        assert isinstance(ScriptedSpotter(), WakeWordSpotter)
        assert isinstance(ScriptedGate(), SpeechGate)


@pytest.mark.unit
class TestOneBreath:
    def test_audio_spoken_before_the_wake_word_fires_is_kept(self) -> None:
        """The whole point: words said in the same breath must survive."""
        source = ScriptedSource([b"\x01\x01", b"\x02\x02", b"\x03\x03"])
        capturer = _capturer(
            source=source,
            spotter=ScriptedSpotter(fire_on_read=2),
            gate=ScriptedGate(["end"]),
        )

        delivered, received = _captured(capturer)

        assert delivered is True
        # Both pre-wake chunks are present, so nothing was lost to detection.
        assert received[0].samples.tobytes().startswith(b"\x01\x01\x02\x02")

    def test_the_chunk_that_completed_the_wake_word_is_retained(self) -> None:
        source = ScriptedSource([b"\xaa\xaa"])
        capturer = _capturer(
            source=source,
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate(["end"]),
        )

        _delivered, received = _captured(capturer)

        assert received[0].samples.tobytes().startswith(b"\xaa\xaa")

    def test_the_stream_is_never_closed_between_the_two_stages(self) -> None:
        """Closing the device is what lost the audio in the first place."""
        source = ScriptedSource([])
        capturer = _capturer(source=source)

        _captured(capturer)

        assert source.closed == 0
        assert source.opened == 0

    def test_retained_audio_counts_as_speech_already_under_way(self) -> None:
        """A gate never reporting "start" must still end a running utterance."""
        source = ScriptedSource([b"\x01\x01"])
        capturer = _capturer(
            source=source,
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate([None, "end"]),
        )

        delivered, _received = _captured(capturer)

        assert delivered is True


@pytest.mark.unit
class TestDelivery:
    def test_delivers_audio_at_the_configured_rate(self) -> None:
        capturer = _capturer(source=ScriptedSource([]))

        _delivered, received = _captured(capturer)

        assert received[0].sample_rate == 8
        assert received[0].channels == 1

    def test_delivers_int16_samples(self) -> None:
        capturer = _capturer(source=ScriptedSource([]))

        _delivered, received = _captured(capturer)

        assert received[0].samples.dtype == np.int16

    def test_recognisers_are_reset_before_each_attempt(self) -> None:
        """Leftover state from the previous turn causes phantom detections."""
        spotter = ScriptedSpotter()
        gate = ScriptedGate(["end"])
        capturer = _capturer(source=ScriptedSource([]), spotter=spotter, gate=gate)

        capturer.capture_utterance(lambda _audio: None)

        assert spotter.resets == 1
        assert gate.resets == 1

    def test_the_buffer_does_not_leak_into_the_next_turn(self) -> None:
        preroll = RollingAudioBuffer(max_seconds=1.0, rate=8, sample_width=2)
        capturer = _capturer(
            source=ScriptedSource([b"\x09\x09"]),
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate(["end"]),
            preroll=preroll,
        )

        capturer.capture_utterance(lambda _audio: None)

        assert len(preroll) == 0


@pytest.mark.unit
class TestSpeechOnsetAfterWaking:
    def test_speech_starting_after_the_wake_word_is_captured(self) -> None:
        """The old two-beat interaction must keep working."""
        empty = RollingAudioBuffer(max_seconds=1.0, rate=8, sample_width=2)
        source = ScriptedSource([b"", b"\x05\x05", b"\x06\x06"])
        capturer = _capturer(
            source=source,
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate([None, "start", "end"]),
            preroll=empty,
        )

        delivered, received = _captured(capturer)

        assert delivered is True
        assert len(received[0].samples) > 0


@pytest.mark.unit
class TestTimeouts:
    def test_gives_up_when_the_wake_word_never_comes(self) -> None:
        clock = ManualClock()
        never = ScriptedSpotter(fire_on_read=None)
        capturer = _capturer(
            source=ScriptedSource([]),
            spotter=never,
            clock=clock,
            wake_timeout_s=0.0,
        )

        delivered, received = _captured(capturer)

        assert delivered is False
        assert received == []

    def test_reports_nothing_said_after_the_wake_word(self) -> None:
        """No retained audio and no speech means there is no turn to run."""
        clock = ManualClock()
        empty = RollingAudioBuffer(max_seconds=1.0, rate=8, sample_width=2)
        capturer = _capturer(
            source=ScriptedSource([b""]),
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate([]),
            preroll=empty,
            clock=clock,
            utterance_timeout_s=0.0,
        )

        delivered, received = _captured(capturer)

        assert delivered is False
        assert received == []

    def test_a_long_utterance_is_delivered_rather_than_dropped(self) -> None:
        """Clipping a long request beats silently losing the whole turn."""
        ticking = ManualClock()

        def clock() -> float:
            now = ticking.now
            ticking.now += 0.4
            return now

        capturer = _capturer(
            source=ScriptedSource([b"\x07\x07"]),
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate([]),  # never reports an end
            clock=clock,
            wake_timeout_s=10.0,
            utterance_timeout_s=1.0,
        )

        delivered, received = _captured(capturer)

        assert delivered is True
        assert len(received[0].samples) > 0

    def test_an_end_without_any_speech_does_not_deliver(self) -> None:
        clock = ManualClock()
        empty = RollingAudioBuffer(max_seconds=1.0, rate=8, sample_width=2)
        capturer = _capturer(
            source=ScriptedSource([b""]),
            spotter=ScriptedSpotter(fire_on_read=1),
            gate=ScriptedGate(["end"]),
            preroll=empty,
            clock=clock,
            utterance_timeout_s=0.0,
        )

        delivered, _received = _captured(capturer)

        assert delivered is False


@pytest.mark.unit
class TestDefaults:
    def test_a_buffer_is_created_when_none_is_supplied(self) -> None:
        capturer = OneBreathCapturer(
            audio_source=ScriptedSource([]),
            spotter=ScriptedSpotter(),
            speech_gate=ScriptedGate(["end"]),
            chunk=1,
            clock=lambda: 0.0,
            announce=lambda _message: None,
        )

        assert capturer.capture_utterance(lambda _audio: None) is True


@pytest.mark.unit
class TestStripWakePhrase:
    PHRASES = ("hey jarvis", "jarvis")

    def test_a_leading_wake_phrase_is_removed(self) -> None:
        assert (
            strip_wake_phrase("Hey Jarvis, switch to driving mode.", self.PHRASES)
            == "switch to driving mode."
        )

    def test_matching_ignores_case(self) -> None:
        assert strip_wake_phrase("HEY JARVIS stop", self.PHRASES) == "stop"

    def test_punctuation_between_the_phrase_and_request_is_dropped(self) -> None:
        assert strip_wake_phrase("Hey Jarvis... next", self.PHRASES) == "next"

    def test_a_transcript_without_the_phrase_is_left_alone(self) -> None:
        assert (
            strip_wake_phrase("switch to home mode.", self.PHRASES)
            == "switch to home mode."
        )

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        assert strip_wake_phrase("   next   ", self.PHRASES) == "next"

    def test_a_wake_phrase_alone_leaves_nothing(self) -> None:
        """The caller uses the empty result to know no request was made."""
        assert strip_wake_phrase("Hey Jarvis.", self.PHRASES) == ""

    def test_the_phrase_is_only_stripped_from_the_front(self) -> None:
        assert (
            strip_wake_phrase("tell jarvis hello", self.PHRASES) == "tell jarvis hello"
        )

    def test_the_first_matching_phrase_wins(self) -> None:
        assert strip_wake_phrase("Jarvis, repeat", self.PHRASES) == "repeat"

    def test_no_phrases_configured_leaves_the_transcript_intact(self) -> None:
        assert strip_wake_phrase("Hey Jarvis, next", ()) == "Hey Jarvis, next"
