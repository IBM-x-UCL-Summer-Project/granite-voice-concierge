# Third-party
import pytest

# Local
from voice_concierge.command_control.fakes import (
    FakeCommandSpotter,
    FakePhraseRecognizer,
    FakePlaybackController,
)
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PhraseRecognizer,
    PlaybackController,
)
from voice_concierge.command_control.types import CommandEvent


class TestFakeCommandSpotter:
    """Unit tests for the FakeCommandSpotter."""

    @pytest.mark.unit
    def test_emits_scripted_events_then_none(self) -> None:
        """The fake returns scripted events in order, then None when exhausted."""
        event = CommandEvent(command="stop", phrase="stop")
        spotter = FakeCommandSpotter([event, None])

        assert spotter.process(b"a") is event
        assert spotter.process(b"b") is None
        assert spotter.process(b"c") is None  # exhausted

    @pytest.mark.unit
    def test_records_frames(self) -> None:
        """The fake records every frame it processes."""
        spotter = FakeCommandSpotter()

        spotter.process(b"x")
        spotter.process(b"y")

        assert spotter.frames == [b"x", b"y"]

    @pytest.mark.unit
    def test_satisfies_command_spotter_protocol(self) -> None:
        """The fake satisfies the runtime-checkable CommandSpotter protocol."""
        assert isinstance(FakeCommandSpotter(), CommandSpotter)


class TestFakePhraseRecognizer:
    """Unit tests for the FakePhraseRecognizer."""

    @pytest.mark.unit
    def test_returns_scripted_phrases_then_none(self) -> None:
        """The fake returns scripted phrases in order, then None."""
        recognizer = FakePhraseRecognizer(["stop", None])

        assert recognizer.recognize(b"a") == "stop"
        assert recognizer.recognize(b"b") is None
        assert recognizer.recognize(b"c") is None  # exhausted

    @pytest.mark.unit
    def test_records_frames(self) -> None:
        """The fake records every frame it processes."""
        recognizer = FakePhraseRecognizer()

        recognizer.recognize(b"x")

        assert recognizer.frames == [b"x"]

    @pytest.mark.unit
    def test_satisfies_phrase_recognizer_protocol(self) -> None:
        """The fake satisfies the runtime-checkable PhraseRecognizer protocol."""
        assert isinstance(FakePhraseRecognizer(), PhraseRecognizer)


class TestFakePlaybackController:
    """Unit tests for the FakePlaybackController."""

    @pytest.mark.unit
    def test_records_actions_in_order(self) -> None:
        """The fake records stop/pause/resume calls in order."""
        controller = FakePlaybackController()

        controller.pause()
        controller.resume()
        controller.stop()

        assert controller.actions == ["pause", "resume", "stop"]

    @pytest.mark.unit
    def test_satisfies_playback_controller_protocol(self) -> None:
        """The fake satisfies the runtime-checkable PlaybackController protocol."""
        assert isinstance(FakePlaybackController(), PlaybackController)
