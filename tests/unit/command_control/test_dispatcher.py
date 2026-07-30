# Third-party
import pytest

# Local
from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.fakes import FakePlaybackController
from voice_concierge.command_control.types import CommandEvent


class TestCommandDispatcher:
    """Unit tests for the CommandDispatcher fast-lane routing."""

    @pytest.mark.unit
    def test_dispatches_stop(self) -> None:
        """A stop command routes to the controller's stop()."""
        controller = FakePlaybackController()
        CommandDispatcher(controller).dispatch(
            CommandEvent(command="stop", phrase="stop")
        )

        assert controller.actions == ["stop"]

    @pytest.mark.unit
    def test_dispatches_pause(self) -> None:
        """A pause command routes to the controller's pause()."""
        controller = FakePlaybackController()
        CommandDispatcher(controller).dispatch(
            CommandEvent(command="pause", phrase="wait")
        )

        assert controller.actions == ["pause"]

    @pytest.mark.unit
    def test_dispatches_resume(self) -> None:
        """A resume command routes to the controller's resume()."""
        controller = FakePlaybackController()
        CommandDispatcher(controller).dispatch(
            CommandEvent(command="resume", phrase="continue")
        )

        assert controller.actions == ["resume"]
