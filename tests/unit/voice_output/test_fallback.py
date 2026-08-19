# tests/unit/voice_output/test_fallback.py
# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.fallback import FallbackTextToSpeech
from voice_concierge.voice_output.interfaces import TextToSpeech


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(2, dtype=np.int16), sample_rate=16000, channels=1
    )


class Voice:
    """Records what it said, and can be made to fail."""

    def __init__(self, name: str, *, broken: bool = False) -> None:
        self.name = name
        self.said: list[str] = []
        self._broken = broken

    def synthesize(self, text: str) -> CapturedAudio:
        if self._broken:
            raise RuntimeError(f"{self.name} is broken")
        self.said.append(text)
        return _audio()


@pytest.mark.unit
class TestConformance:
    def test_the_wrapper_is_a_text_to_speech(self) -> None:
        wrapper = FallbackTextToSpeech(Voice("piper"), lambda: Voice("say"))

        assert isinstance(wrapper, TextToSpeech)


@pytest.mark.unit
class TestPreferredVoice:
    def test_a_working_preferred_voice_is_used(self) -> None:
        piper = Voice("piper")
        wrapper = FallbackTextToSpeech(piper, lambda: Voice("say"))

        wrapper.synthesize("hello")

        assert piper.said == ["hello"]
        assert wrapper.using_fallback is False

    def test_the_spare_is_never_built_while_the_preferred_works(self) -> None:
        built = 0

        def build_spare() -> Voice:
            nonlocal built
            built += 1
            return Voice("say")

        wrapper = FallbackTextToSpeech(Voice("piper"), build_spare)
        wrapper.synthesize("hello")

        assert built == 0


@pytest.mark.unit
class TestFallingBack:
    def test_a_failing_preferred_voice_still_produces_speech(self) -> None:
        """The app fell silent for a whole session before this existed."""
        spare = Voice("say")
        wrapper = FallbackTextToSpeech(Voice("piper", broken=True), lambda: spare)

        wrapper.synthesize("hello")

        assert spare.said == ["hello"]
        assert wrapper.using_fallback is True

    def test_the_preferred_voice_is_not_retried(self) -> None:
        """Retrying would pay the same failure on every utterance."""
        piper = Voice("piper", broken=True)
        spare = Voice("say")
        wrapper = FallbackTextToSpeech(piper, lambda: spare)

        wrapper.synthesize("one")
        wrapper.synthesize("two")

        assert spare.said == ["one", "two"]

    def test_the_spare_is_built_once(self) -> None:
        built = 0

        def build_spare() -> Voice:
            nonlocal built
            built += 1
            return Voice("say")

        wrapper = FallbackTextToSpeech(Voice("piper", broken=True), build_spare)
        wrapper.synthesize("one")
        wrapper.synthesize("two")

        assert built == 1

    def test_the_switch_is_reported_once(self) -> None:
        seen: list[Exception] = []
        wrapper = FallbackTextToSpeech(
            Voice("piper", broken=True),
            lambda: Voice("say"),
            on_fallback=seen.append,
        )

        wrapper.synthesize("one")
        wrapper.synthesize("two")

        assert len(seen) == 1
        assert "broken" in str(seen[0])

    def test_the_switch_can_go_unreported(self) -> None:
        wrapper = FallbackTextToSpeech(
            Voice("piper", broken=True), lambda: Voice("say")
        )

        assert wrapper.synthesize("one") is not None

    def test_a_failing_spare_is_not_hidden(self) -> None:
        """Both voices broken is a real fault the caller must see."""
        wrapper = FallbackTextToSpeech(
            Voice("piper", broken=True), lambda: Voice("say", broken=True)
        )

        with pytest.raises(RuntimeError, match="say is broken"):
            wrapper.synthesize("hello")
