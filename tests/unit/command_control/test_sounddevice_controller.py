# Standard library
import sys
import types
from unittest.mock import MagicMock

# Third-party
import pytest

# Local
from voice_concierge.command_control.errors import PlaybackControlError
from voice_concierge.command_control.interfaces import PlaybackController
from voice_concierge.command_control.sounddevice_controller import (
    SoundDevicePlaybackController,
)


class TestSoundDevicePlaybackController:
    """Unit tests for the SoundDevice-backed playback controller."""

    @pytest.mark.unit
    def test_stop_calls_sounddevice_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stop() aborts the active playback via sounddevice.stop()."""
        fake_sd = types.SimpleNamespace(stop=MagicMock())
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

        SoundDevicePlaybackController().stop()

        fake_sd.stop.assert_called_once_with()

    @pytest.mark.unit
    def test_stop_without_sounddevice_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing sounddevice dependency raises PlaybackControlError."""
        monkeypatch.setitem(sys.modules, "sounddevice", None)

        with pytest.raises(PlaybackControlError):
            SoundDevicePlaybackController().stop()

    @pytest.mark.unit
    def test_pause_and_resume_are_noops(self) -> None:
        """pause()/resume() do nothing on this stop-only backend."""
        controller = SoundDevicePlaybackController()

        assert controller.pause() is None
        assert controller.resume() is None

    @pytest.mark.unit
    def test_satisfies_playback_controller_protocol(self) -> None:
        """The controller satisfies the runtime-checkable protocol."""
        assert isinstance(SoundDevicePlaybackController(), PlaybackController)
