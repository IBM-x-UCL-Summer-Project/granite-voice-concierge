# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio.player import AudioPlayer
from voice_concierge.audio.voice_processing_player import (
    VoiceProcessingAudioPlayer,
    _format_error,
    mic_to_command_bytes,
    resample_int16_to_float,
)


class _FakeNSError:
    """Stand-in for an AVFoundation NSError with pyobjc-style accessors."""

    def __init__(self, code: int, description: str) -> None:
        self._code = code
        self._description = description

    def code(self) -> int:
        return self._code

    def localizedDescription(self) -> str:
        return self._description


class TestFormatError:
    """Unit tests for turning an NSError into a debuggable string."""

    @pytest.mark.unit
    def test_none_reports_missing_detail(self) -> None:
        assert "no error detail" in _format_error(None)

    @pytest.mark.unit
    def test_nserror_includes_code_and_description(self) -> None:
        out = _format_error(_FakeNSError(-10875, "engine init failed"))
        assert out == "code -10875; engine init failed"

    @pytest.mark.unit
    def test_plain_object_falls_back_to_str(self) -> None:
        assert _format_error("raw message") == "raw message"


class _FakePlayerNode:
    """Records the playback control calls made on it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("stop")

    def pause(self) -> None:
        self.calls.append("pause")

    def play(self) -> None:
        self.calls.append("play")


class TestMicToCommandBytes:
    """Unit tests for the microphone downsample/format conversion."""

    @pytest.mark.unit
    def test_downsamples_48k_to_16k(self) -> None:
        mono = np.zeros(4800, dtype=np.float32)
        out = np.frombuffer(mic_to_command_bytes(mono, 48000), dtype=np.int16)
        assert len(out) == 1600  # 48000 -> 16000 is a factor of 3

    @pytest.mark.unit
    def test_passthrough_when_already_16k(self) -> None:
        mono = np.zeros(1600, dtype=np.float32)
        out = np.frombuffer(mic_to_command_bytes(mono, 16000), dtype=np.int16)
        assert len(out) == 1600  # no resample

    @pytest.mark.unit
    def test_scales_and_clips_to_int16(self) -> None:
        mono = np.array([0.0, 1.0, -1.0, 2.0], dtype=np.float32)
        out = np.frombuffer(mic_to_command_bytes(mono, 16000), dtype=np.int16)
        assert out[0] == 0
        assert out[3] == 32767  # 2.0 clipped to the int16 max


class TestResample:
    """Unit tests for the playback resampler."""

    @pytest.mark.unit
    def test_same_rate_is_passthrough(self) -> None:
        samples = np.array([16384, -16384], dtype=np.int16)
        out = resample_int16_to_float(samples, 16000, 16000)
        assert np.allclose(out, [0.5, -0.5], atol=1e-4)

    @pytest.mark.unit
    def test_upsamples_to_a_higher_rate(self) -> None:
        samples = np.zeros(100, dtype=np.int16)
        out = resample_int16_to_float(samples, 22050, 48000)
        assert len(out) == round(100 * 48000 / 22050)
        assert out.dtype == np.float32


class TestPlaybackControlQueue:
    """Unit tests for the command queue and the per-iteration pump."""

    @pytest.mark.unit
    def test_satisfies_audio_player_protocol(self) -> None:
        assert isinstance(VoiceProcessingAudioPlayer(), AudioPlayer)

    @pytest.mark.unit
    def test_satisfies_playback_controller_protocol(self) -> None:
        from voice_concierge.command_control import PlaybackController

        assert isinstance(VoiceProcessingAudioPlayer(), PlaybackController)

    @pytest.mark.unit
    def test_record_and_take_returns_last_command_then_clears(self) -> None:
        player = VoiceProcessingAudioPlayer()
        player.pause()
        player.stop()  # latest wins
        assert player._take() == "stop"
        assert player._take() is None  # cleared

    @pytest.mark.unit
    def test_pump_stop_command_returns_true_and_stops_node(self) -> None:
        player = VoiceProcessingAudioPlayer()
        node = _FakePlayerNode()
        player.stop()
        assert player._pump_once(node, None) is True
        assert node.calls == ["stop"]

    @pytest.mark.unit
    def test_pump_pause_then_resume_drives_the_node(self) -> None:
        player = VoiceProcessingAudioPlayer()
        node = _FakePlayerNode()

        assert player.is_paused is False
        player.pause()
        assert player._pump_once(node, None) is False
        assert player.is_paused is True  # pause holds the deadline open
        player.resume()
        assert player._pump_once(node, None) is False
        assert player.is_paused is False  # resume lets it count down again

        assert node.calls == ["pause", "play"]

    @pytest.mark.unit
    def test_pump_delivers_a_queued_input_frame(self) -> None:
        player = VoiceProcessingAudioPlayer()
        node = _FakePlayerNode()
        player._input_queue.put_nowait(b"frame")
        received: list[bytes] = []

        assert player._pump_once(node, received.append) is False

        assert received == [b"frame"]
        assert node.calls == []  # no command was pending

    @pytest.mark.unit
    def test_pump_without_frames_or_commands_is_a_noop(self) -> None:
        player = VoiceProcessingAudioPlayer()
        node = _FakePlayerNode()
        received: list[bytes] = []

        assert player._pump_once(node, received.append) is False  # empty queue

        assert received == []
        assert node.calls == []

    @pytest.mark.unit
    def test_drain_input_clears_stale_frames(self) -> None:
        player = VoiceProcessingAudioPlayer()
        player._input_queue.put_nowait(b"a")
        player._input_queue.put_nowait(b"b")
        player._drain_input()
        assert player._input_queue.empty()


class TestEchoCancellationAvailability:
    """The probe callers use before assembling a barge-in stack."""

    @pytest.mark.unit
    def test_reports_true_when_the_bindings_are_importable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import voice_concierge.audio.voice_processing_player as module

        monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: object())
        assert module.echo_cancellation_available() is True

    @pytest.mark.unit
    def test_reports_false_when_the_bindings_are_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller must be able to fall back before it starts speaking."""
        import voice_concierge.audio.voice_processing_player as module

        monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: None)
        assert module.echo_cancellation_available() is False
