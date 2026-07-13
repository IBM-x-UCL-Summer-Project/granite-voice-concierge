# Standard library
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import FakeAudioSource
from voice_concierge.command_control import (
    CommandListener,
    FakeCommandSpotter,
    FakePlaybackController,
    build_command_listener,
)
from voice_concierge.command_control.types import CommandEvent

_FRAME = np.zeros(512, dtype=np.int16).tobytes()


class TestBuildCommandListener:
    """Unit tests for the build_command_listener factory."""

    @pytest.mark.unit
    def test_wires_spotter_dispatch_to_controller(self) -> None:
        """A spotted event flows through the dispatcher to the controller."""
        event = CommandEvent(command="stop", phrase="stop")
        controller = FakePlaybackController()
        listener = build_command_listener(
            FakeCommandSpotter([event]),
            controller,
            audio_source=FakeAudioSource(fill=_FRAME),
        )

        listener._pump()  # drive one frame: spotter -> dispatch -> controller

        assert isinstance(listener, CommandListener)
        assert controller.actions == ["stop"]

    @pytest.mark.unit
    @patch("voice_concierge.command_control.factory.PyAudioSource")
    def test_builds_default_pyaudio_source(self, mock_source: patch) -> None:
        """Without an injected source, a PyAudioSource is created for the chunk."""
        build_command_listener(
            FakeCommandSpotter(), FakePlaybackController(), chunk=256
        )

        mock_source.assert_called_once_with(frames_per_buffer=256)
