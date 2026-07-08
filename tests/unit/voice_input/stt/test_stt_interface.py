# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.stt import (
    DeterministicSpeechToTextFake,
    SpeechToText,
    Transcript,
)


def _audio() -> CapturedAudio:
    """Return a short silent utterance for transcription tests."""
    return CapturedAudio(samples=np.zeros(320, dtype=np.int16))


class TestDeterministicSpeechToTextFake:
    """Unit tests for the deterministic SpeechToText fake."""

    @pytest.mark.unit
    def test_returns_default_transcript_and_records_audio(self) -> None:
        """The fake returns a default transcript and records received audio."""
        fake = DeterministicSpeechToTextFake()
        audio = _audio()

        result = fake.transcribe(audio)

        assert result.text == "deterministic transcript"
        assert fake.calls == [audio]

    @pytest.mark.unit
    def test_returns_supplied_transcript(self) -> None:
        """The fake returns a caller-supplied transcript unchanged."""
        transcript = Transcript(text="hello", language="en")
        fake = DeterministicSpeechToTextFake(transcript=transcript)

        assert fake.transcribe(_audio()) is transcript

    @pytest.mark.unit
    def test_satisfies_speech_to_text_protocol(self) -> None:
        """The fake satisfies the runtime-checkable SpeechToText protocol."""
        assert isinstance(DeterministicSpeechToTextFake(), SpeechToText)
