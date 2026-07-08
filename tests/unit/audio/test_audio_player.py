# Standard library
import sys
import types
from unittest.mock import MagicMock

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import (
    AudioDeviceError,
    AudioPlayer,
    CapturedAudio,
    FakeAudioPlayer,
    SoundDevicePlayer,
)


def _audio() -> CapturedAudio:
    """Return a short silent utterance for playback tests."""
    return CapturedAudio(samples=np.zeros(320, dtype=np.int16), sample_rate=16000)


class TestFakeAudioPlayer:
    """Unit tests for the in-memory FakeAudioPlayer."""

    @pytest.mark.unit
    def test_records_played_audio(self) -> None:
        """play() appends each played utterance to `played`."""
        player = FakeAudioPlayer()
        audio = _audio()

        player.play(audio)

        assert player.played == [audio]


class TestSoundDevicePlayer:
    """Unit tests for the sounddevice-backed AudioPlayer."""

    @pytest.mark.unit
    def test_play_invokes_sounddevice_and_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """play() calls sd.play with the samples/rate then blocks on sd.wait."""
        fake_sd = types.SimpleNamespace(play=MagicMock(), wait=MagicMock())
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
        audio = _audio()

        SoundDevicePlayer().play(audio)

        fake_sd.play.assert_called_once_with(audio.samples, audio.sample_rate)
        fake_sd.wait.assert_called_once_with()

    @pytest.mark.unit
    def test_missing_sounddevice_raises_audio_device_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing sounddevice dependency raises AudioDeviceError."""
        monkeypatch.setitem(sys.modules, "sounddevice", None)

        with pytest.raises(AudioDeviceError):
            SoundDevicePlayer().play(_audio())

    @pytest.mark.unit
    def test_playback_failure_raises_audio_device_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure inside sounddevice playback is wrapped in AudioDeviceError."""
        fake_sd = types.SimpleNamespace(
            play=MagicMock(side_effect=RuntimeError("boom")), wait=MagicMock()
        )
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

        with pytest.raises(AudioDeviceError):
            SoundDevicePlayer().play(_audio())


class TestAudioPlayerProtocol:
    """The concrete players satisfy the runtime-checkable protocol."""

    @pytest.mark.unit
    def test_players_satisfy_protocol(self) -> None:
        """FakeAudioPlayer and SoundDevicePlayer are AudioPlayer instances."""
        assert isinstance(FakeAudioPlayer(), AudioPlayer)
        assert isinstance(SoundDevicePlayer(), AudioPlayer)
