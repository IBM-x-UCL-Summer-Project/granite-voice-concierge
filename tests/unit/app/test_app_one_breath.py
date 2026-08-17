# tests/unit/app/test_app_one_breath.py
# Standard library
from dataclasses import dataclass

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.app.one_breath import (
    DEFAULT_WAKE_PHRASES,
    WakePhraseStrippingSpeechToText,
)
from voice_concierge.app.types import SpeechToTextAdapter
from voice_concierge.audio import CapturedAudio


@dataclass(frozen=True)
class FakeTranscript:
    text: str
    language: str | None = "en"
    language_probability: float | None = 0.99


class FakeSpeechToText:
    """Returns a fixed transcript, ignoring the audio."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def transcribe(self, audio: CapturedAudio) -> FakeTranscript:
        self.calls += 1
        return FakeTranscript(text=self._text)


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(4, dtype=np.int16), sample_rate=16000, channels=1
    )


def _transcribe(spoken: str) -> str:
    stt = WakePhraseStrippingSpeechToText(FakeSpeechToText(spoken))
    return stt.transcribe(_audio()).text


@pytest.mark.unit
class TestConformance:
    def test_the_wrapper_is_usable_wherever_the_stt_boundary_is_expected(
        self,
    ) -> None:
        """SpeechToTextAdapter is not runtime_checkable, so exercise it instead."""

        def take_adapter(adapter: SpeechToTextAdapter) -> str:
            return adapter.transcribe(_audio()).text

        wrapper = WakePhraseStrippingSpeechToText(FakeSpeechToText("Jarvis, hello"))

        assert take_adapter(wrapper) == "hello"


@pytest.mark.unit
class TestStripping:
    def test_a_leading_wake_phrase_is_removed(self) -> None:
        assert _transcribe("Hey Jarvis, next") == "next"

    def test_an_anchored_mode_switch_survives_the_wake_phrase(self) -> None:
        """The reason this wrapper exists: mode matching is whole-utterance."""
        assert _transcribe("Hey Jarvis, switch to driving mode.") == (
            "switch to driving mode."
        )

    def test_a_transcript_without_a_wake_phrase_is_untouched(self) -> None:
        assert _transcribe("walk me through making eggs") == (
            "walk me through making eggs"
        )

    def test_the_backend_result_is_passed_through_when_unchanged(self) -> None:
        """No copy is made when there is nothing to strip."""
        inner = FakeSpeechToText("stop")
        wrapper = WakePhraseStrippingSpeechToText(inner)

        result = wrapper.transcribe(_audio())

        assert isinstance(result, FakeTranscript)

    def test_language_metadata_survives_stripping(self) -> None:
        wrapper = WakePhraseStrippingSpeechToText(FakeSpeechToText("Jarvis, stop"))

        result = wrapper.transcribe(_audio())

        assert result.text == "stop"
        assert result.language == "en"
        assert result.language_probability == pytest.approx(0.99)

    def test_a_wake_phrase_alone_leaves_an_empty_transcript(self) -> None:
        assert _transcribe("Hey Jarvis.") == ""

    def test_the_backend_is_called_once_per_turn(self) -> None:
        inner = FakeSpeechToText("Hey Jarvis, next")
        wrapper = WakePhraseStrippingSpeechToText(inner)

        wrapper.transcribe(_audio())

        assert inner.calls == 1

    def test_custom_phrases_replace_the_defaults(self) -> None:
        wrapper = WakePhraseStrippingSpeechToText(
            FakeSpeechToText("Computer, stop"), phrases=("computer",)
        )

        assert wrapper.transcribe(_audio()).text == "stop"


@pytest.mark.unit
class TestDefaultPhrases:
    @pytest.mark.parametrize(
        "spoken",
        ["Hey Jarvis, stop", "Hey, Jarvis stop", "Hi Jarvis stop", "Jarvis stop"],
    )
    def test_common_recogniser_spellings_are_all_handled(self, spoken: str) -> None:
        """Whisper renders the wake phrase inconsistently across takes."""
        assert _transcribe(spoken) == "stop"

    def test_the_bare_name_is_covered(self) -> None:
        assert "jarvis" in DEFAULT_WAKE_PHRASES
