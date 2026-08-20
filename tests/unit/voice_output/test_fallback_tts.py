"""Tests for ordered text-to-speech fallback."""

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output import (
    DeterministicTextToSpeechFake,
    FallbackTextToSpeech,
    TextToSpeech,
    TextToSpeechBackendUnavailableError,
    TextToSpeechSynthesisError,
)


class FailingTextToSpeech:
    """Text-to-speech test double that records and raises a configured error."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[str] = []

    def synthesize(self, text: str) -> CapturedAudio:
        self.calls.append(text)
        raise self.error


def audible_text_to_speech_fake() -> DeterministicTextToSpeechFake:
    return DeterministicTextToSpeechFake(
        CapturedAudio(samples=np.ones(160, dtype=np.int16))
    )


@pytest.mark.unit
def test_uses_fallback_after_expected_backend_failure() -> None:
    primary = FailingTextToSpeech(TextToSpeechSynthesisError("Piper failed"))
    fallback = audible_text_to_speech_fake()
    engine = FallbackTextToSpeech(primary, fallback)

    audio = engine.synthesize("hello")

    assert audio is fallback.audio
    assert primary.calls == ["hello"]
    assert fallback.calls == ["hello"]


@pytest.mark.unit
def test_stops_after_first_successful_backend() -> None:
    primary = audible_text_to_speech_fake()
    fallback = audible_text_to_speech_fake()

    audio = FallbackTextToSpeech(primary, fallback).synthesize("hello")

    assert audio is primary.audio
    assert primary.calls == ["hello"]
    assert fallback.calls == []


@pytest.mark.unit
def test_treats_silent_audio_as_a_backend_failure() -> None:
    silent_primary = DeterministicTextToSpeechFake()
    fallback = audible_text_to_speech_fake()

    audio = FallbackTextToSpeech(silent_primary, fallback).synthesize("hello")

    assert audio is fallback.audio
    assert fallback.calls == ["hello"]


@pytest.mark.unit
def test_raises_last_error_when_all_backends_fail() -> None:
    primary = FailingTextToSpeech(
        TextToSpeechBackendUnavailableError("Piper unavailable")
    )
    final_error = TextToSpeechSynthesisError("say failed")
    fallback = FailingTextToSpeech(final_error)

    with pytest.raises(TextToSpeechSynthesisError) as captured:
        FallbackTextToSpeech(primary, fallback).synthesize("hello")

    assert captured.value is final_error


@pytest.mark.unit
def test_does_not_hide_unexpected_backend_errors() -> None:
    primary = FailingTextToSpeech(ValueError("programming error"))
    fallback = DeterministicTextToSpeechFake()

    with pytest.raises(ValueError, match="programming error"):
        FallbackTextToSpeech(primary, fallback).synthesize("hello")

    assert fallback.calls == []


@pytest.mark.unit
def test_requires_at_least_one_backend() -> None:
    with pytest.raises(ValueError, match="At least one"):
        FallbackTextToSpeech()


@pytest.mark.unit
def test_satisfies_text_to_speech_protocol() -> None:
    assert isinstance(
        FallbackTextToSpeech(DeterministicTextToSpeechFake()),
        TextToSpeech,
    )
