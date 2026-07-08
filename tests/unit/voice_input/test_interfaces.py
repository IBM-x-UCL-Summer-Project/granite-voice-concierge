# Third-party
import pytest

# Local
from voice_concierge.voice_input.interfaces import UtteranceCapturer, WakeWordListener


class _Listener:
    """Stub implementing only the WakeWordListener method."""

    def listen(self, on_wake_word) -> None:
        on_wake_word()


class _Capturer:
    """Stub implementing only the UtteranceCapturer method."""

    def capture_utterance(self, on_utterance_captured) -> None:
        return None


class TestVoiceInputInterfaces:
    """Unit tests for the voice input stage protocols."""

    @pytest.mark.unit
    def test_wake_word_listener_protocol(self) -> None:
        """Only a type exposing listen() satisfies WakeWordListener."""
        assert isinstance(_Listener(), WakeWordListener)
        assert not isinstance(_Capturer(), WakeWordListener)

    @pytest.mark.unit
    def test_utterance_capturer_protocol(self) -> None:
        """Only a type exposing capture_utterance() satisfies UtteranceCapturer."""
        assert isinstance(_Capturer(), UtteranceCapturer)
        assert not isinstance(_Listener(), UtteranceCapturer)
