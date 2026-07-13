# Third-party
import pytest

# Local
from voice_concierge.command_control.fakes import (
    FakeCommandSpotter,
    FakePlaybackController,
)
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
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
