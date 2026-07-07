# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output import DeterministicTextToSpeechFake, TextToSpeech


class TestDeterministicTextToSpeechFake:
    """Unit tests for the deterministic TextToSpeech fake."""

    @pytest.mark.unit
    def test_returns_default_audio_and_records_text(self) -> None:
        """The fake returns default audio and records requested text."""
        fake = DeterministicTextToSpeechFake()

        audio = fake.synthesize("hello")

        assert isinstance(audio, CapturedAudio)
        assert fake.calls == ["hello"]

    @pytest.mark.unit
    def test_returns_supplied_audio(self) -> None:
        """The fake returns caller-supplied audio unchanged."""
        supplied = CapturedAudio(samples=np.zeros(8, dtype=np.int16))
        fake = DeterministicTextToSpeechFake(audio=supplied)

        assert fake.synthesize("hi") is supplied

    @pytest.mark.unit
    def test_satisfies_text_to_speech_protocol(self) -> None:
        """The fake satisfies the runtime-checkable TextToSpeech protocol."""
        assert isinstance(DeterministicTextToSpeechFake(), TextToSpeech)
