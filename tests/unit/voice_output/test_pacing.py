# tests/unit/voice_output/test_pacing.py
# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.pacing import (
    DEFAULT_PACE_LEVEL,
    PACE_LADDER,
    PacedTextToSpeech,
    SpeechRate,
    acknowledgement,
)


class _Backend:
    """Records the rate it was built at and what it was asked to say."""

    def __init__(self, rate_wpm: int) -> None:
        self.rate_wpm = rate_wpm
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> CapturedAudio:
        self.spoken.append(text)
        return CapturedAudio(
            samples=np.zeros(4, dtype=np.int16), sample_rate=16000, channels=1
        )


def _paced() -> tuple[PacedTextToSpeech, list[_Backend]]:
    built: list[_Backend] = []

    def _build(rate_wpm: int) -> _Backend:
        backend = _Backend(rate_wpm)
        built.append(backend)
        return backend

    return PacedTextToSpeech(_build), built


@pytest.mark.unit
class TestTheLadder:
    def test_a_new_conversation_starts_in_the_middle(self) -> None:
        assert SpeechRate().level == DEFAULT_PACE_LEVEL
        assert SpeechRate().words_per_minute == PACE_LADDER[DEFAULT_PACE_LEVEL]

    def test_slower_steps_down_one_rung(self) -> None:
        assert SpeechRate(2).slower().level == 1

    def test_faster_steps_up_one_rung(self) -> None:
        assert SpeechRate(2).faster().level == 3

    def test_each_rung_is_slower_than_the_next(self) -> None:
        """A ladder that is not ordered would make the commands meaningless."""
        assert list(PACE_LADDER) == sorted(PACE_LADDER)

    def test_the_ladder_stops_at_the_slow_end(self) -> None:
        slowest = SpeechRate(0)

        assert slowest.at_slowest is True
        assert slowest.slower() == slowest  # never becomes unintelligible

    def test_the_ladder_stops_at_the_fast_end(self) -> None:
        fastest = SpeechRate(len(PACE_LADDER) - 1)

        assert fastest.at_fastest is True
        assert fastest.faster() == fastest

    @pytest.mark.parametrize("level", [-1, len(PACE_LADDER)])
    def test_a_rung_off_the_ladder_is_refused(self, level: int) -> None:
        with pytest.raises(ValueError, match="level must be"):
            SpeechRate(level)


@pytest.mark.unit
class TestAcknowledgement:
    def test_slowing_down_is_confirmed(self) -> None:
        assert acknowledgement(SpeechRate(2), SpeechRate(1)) == "Speaking more slowly."

    def test_speeding_up_is_confirmed(self) -> None:
        assert acknowledgement(SpeechRate(2), SpeechRate(3)) == "Speaking faster."

    def test_hitting_the_slow_end_says_so(self) -> None:
        """Silence would read as the command not being heard."""
        assert acknowledgement(SpeechRate(0), SpeechRate(0)) == (
            "That's as slow as I can go."
        )

    def test_hitting_the_fast_end_says_so(self) -> None:
        top = SpeechRate(len(PACE_LADDER) - 1)

        assert acknowledgement(top, top) == "That's as fast as I can go."


@pytest.mark.unit
class TestPacedTextToSpeech:
    def test_it_speaks_at_the_starting_rate(self) -> None:
        paced, built = _paced()

        paced.synthesize("hello")

        assert built[0].rate_wpm == PACE_LADDER[DEFAULT_PACE_LEVEL]
        assert built[0].spoken == ["hello"]

    def test_slowing_down_builds_a_slower_backend(self) -> None:
        paced, built = _paced()
        paced.synthesize("first")

        said = paced.slower()
        paced.synthesize("second")

        assert said == "Speaking more slowly."
        assert built[1].rate_wpm < built[0].rate_wpm
        assert built[1].spoken == ["second"]

    def test_speeding_up_builds_a_faster_backend(self) -> None:
        paced, built = _paced()
        paced.synthesize("first")

        paced.faster()
        paced.synthesize("second")

        assert built[1].rate_wpm > built[0].rate_wpm

    def test_returning_to_a_rung_reuses_its_backend(self) -> None:
        """Moving up and down should not rebuild the voice each time."""
        paced, built = _paced()
        paced.synthesize("a")
        paced.slower()
        paced.synthesize("b")
        paced.faster()
        paced.synthesize("c")

        assert len(built) == 2  # the original rung was reused, not rebuilt

    def test_the_rate_is_readable(self) -> None:
        paced, _ = _paced()

        paced.slower()

        assert paced.rate.level == DEFAULT_PACE_LEVEL - 1

    def test_a_remembered_rate_can_be_restored(self) -> None:
        paced, built = _paced()

        paced.set_rate(SpeechRate(0))
        paced.synthesize("hello")

        assert built[0].rate_wpm == PACE_LADDER[0]

    def test_it_can_start_at_a_given_rate(self) -> None:
        built: list[_Backend] = []
        paced = PacedTextToSpeech(
            lambda wpm: built.append(_Backend(wpm)) or built[-1], rate=SpeechRate(0)
        )

        paced.synthesize("hello")

        assert built[0].rate_wpm == PACE_LADDER[0]

    def test_it_satisfies_the_text_to_speech_protocol(self) -> None:
        paced, _ = _paced()
        assert isinstance(paced, TextToSpeech)


@pytest.mark.unit
class TestBackendBuilders:
    """Each backend expresses speed differently; the ladder must survive that."""

    def test_piper_slows_by_lengthening(self) -> None:
        from voice_concierge.voice_output.factory import (
            REFERENCE_WPM,
            piper_backend_builder,
        )

        build = piper_backend_builder()
        reference = build(REFERENCE_WPM)
        slow = build(PACE_LADDER[0])
        fast = build(PACE_LADDER[-1])

        # Piper's scale is inverted: a larger length scale is slower speech.
        assert slow.length_scale > reference.length_scale
        assert fast.length_scale < reference.length_scale

    def test_say_takes_words_per_minute_directly(self) -> None:
        from voice_concierge.voice_output.factory import say_backend_builder

        backend = say_backend_builder()(PACE_LADDER[0])

        assert backend._rate_wpm == PACE_LADDER[0]

    def test_the_default_paced_voice_starts_in_the_middle(self) -> None:
        from voice_concierge.voice_output.factory import build_paced_text_to_speech

        assert build_paced_text_to_speech().rate.level == DEFAULT_PACE_LEVEL

    def test_a_paced_voice_can_start_at_a_remembered_rate(self) -> None:
        from voice_concierge.voice_output.factory import build_paced_text_to_speech

        paced = build_paced_text_to_speech(rate=SpeechRate(0))

        assert paced.rate.words_per_minute == PACE_LADDER[0]
