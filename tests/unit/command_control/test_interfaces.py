# Third-party
import pytest

# Local
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PhraseRecognizer,
    PlaybackController,
)


class _Spotter:
    """Stub implementing only the CommandSpotter method."""

    def process(self, frame):
        return None


class _Recognizer:
    """Stub implementing only the PhraseRecognizer method."""

    def recognize(self, frame):
        return None


class _Controller:
    """Stub implementing only the PlaybackController methods."""

    def stop(self) -> None:
        return None

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None


class TestCommandControlInterfaces:
    """Unit tests for the command-control protocols."""

    @pytest.mark.unit
    def test_command_spotter_protocol(self) -> None:
        """Only a type exposing process() satisfies CommandSpotter."""
        assert isinstance(_Spotter(), CommandSpotter)
        assert not isinstance(_Controller(), CommandSpotter)

    @pytest.mark.unit
    def test_playback_controller_protocol(self) -> None:
        """Only a type exposing stop/pause/resume satisfies PlaybackController."""
        assert isinstance(_Controller(), PlaybackController)
        assert not isinstance(_Spotter(), PlaybackController)

    @pytest.mark.unit
    def test_phrase_recognizer_protocol(self) -> None:
        """Only a type exposing recognize() satisfies PhraseRecognizer."""
        assert isinstance(_Recognizer(), PhraseRecognizer)
        assert not isinstance(_Spotter(), PhraseRecognizer)
