# Standard library
import threading
import time
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.audio.duplex_player import (
    DuplexAudioPlayer,
    DuplexBackend,
    _sounddevice_duplex_backend,
)
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.player import AudioPlayer

_MIC_MARK = 7  # value the fake stream feeds as microphone input


class _CallbackStop(Exception):
    """Stand-in for sounddevice.CallbackStop."""


class _FakeDuplexStream:
    """Duplex stream that pulls blocks on a thread, feeding a marker mic block."""

    def __init__(self, *, callback, finished_callback, blocksize, channels, **_):
        self._callback = callback
        self._finished_callback = finished_callback
        self._blocksize = blocksize
        self._channels = channels
        self.out_blocks: list[np.ndarray] = []
        self.aborted = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_FakeDuplexStream":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            indata = np.full(
                (self._blocksize, self._channels), _MIC_MARK, dtype=np.int16
            )
            outdata = np.zeros((self._blocksize, self._channels), dtype=np.int16)
            try:
                self._callback(indata, outdata, self._blocksize, None, None)
            except _CallbackStop:
                self.out_blocks.append(outdata.copy())
                break
            self.out_blocks.append(outdata.copy())
            time.sleep(0.002)  # pace like a real-time callback so consumers interleave
        self._finished_callback()

    def abort(self) -> None:
        self.aborted = True
        self._stop.set()


def _audio(num_samples: int = 2048) -> CapturedAudio:
    ramp = np.arange(1, num_samples + 1, dtype=np.int16)
    return CapturedAudio(samples=ramp, sample_rate=16000, channels=1)


def _backend(stream_cls=_FakeDuplexStream) -> DuplexBackend:
    return DuplexBackend(open_stream=stream_cls, callback_stop=_CallbackStop)


class TestDuplexPlayback:
    """Playback and protocol conformance."""

    @pytest.mark.unit
    def test_plays_all_samples_then_returns(self) -> None:
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())
        player.play(_audio(1024))
        assert player._stream is None  # released after playback

    @pytest.mark.unit
    def test_satisfies_audio_player_protocol(self) -> None:
        assert isinstance(DuplexAudioPlayer(), AudioPlayer)

    @pytest.mark.unit
    def test_satisfies_playback_controller_protocol(self) -> None:
        from voice_concierge.command_control import PlaybackController

        assert isinstance(DuplexAudioPlayer(), PlaybackController)

    @pytest.mark.unit
    def test_wraps_backend_failure(self) -> None:
        def _explode(**_):
            raise RuntimeError("no duplex device")

        player = DuplexAudioPlayer(backend=_backend(stream_cls=_explode))
        with pytest.raises(AudioDeviceError):
            player.play(_audio(64))

    @pytest.mark.unit
    @patch("voice_concierge.audio.duplex_player._sounddevice_duplex_backend")
    def test_uses_sounddevice_backend_by_default(self, mock_backend: patch) -> None:
        mock_backend.return_value = _backend()
        DuplexAudioPlayer(blocksize=256).play(_audio(256))
        mock_backend.assert_called_once_with()


class TestDuplexCapture:
    """Microphone capture delivered to the input callback."""

    @pytest.mark.unit
    def test_input_frames_delivered_to_callback(self) -> None:
        received: list[bytes] = []
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())

        player.play(_audio(4096), on_input_frame=received.append)

        assert received  # mic blocks were delivered while playing
        # each delivered block is the marker mic data the fake stream fed
        first = np.frombuffer(received[0], dtype=np.int16)
        assert np.all(first == _MIC_MARK)

    @pytest.mark.unit
    def test_input_callback_can_stop_playback(self) -> None:
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())
        streams: list[_FakeDuplexStream] = []
        original_enter = _FakeDuplexStream.__enter__

        def _capture(self):
            streams.append(self)
            return original_enter(self)

        def _stop_on_first_frame(_frame: bytes) -> None:
            player.stop()

        with patch.object(_FakeDuplexStream, "__enter__", _capture):
            # long audio so it would not finish on its own before the stop
            player.play(_audio(4_000_000), on_input_frame=_stop_on_first_frame)

        assert streams[0].aborted
        assert player._stream is None


class TestDuplexControl:
    """stop / pause / resume behaviour."""

    @pytest.mark.unit
    def test_pause_emits_silence_and_holds_position(self) -> None:
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())
        samples = _audio(4096).samples.reshape(-1, 1)
        callback = player._build_callback(samples, _CallbackStop, capture=False)

        indata = np.zeros((256, 1), dtype=np.int16)
        outdata = np.zeros((256, 1), dtype=np.int16)
        callback(indata, outdata, 256)
        assert player._position == 256

        player.pause()
        paused_out = np.ones((256, 1), dtype=np.int16)
        callback(indata, paused_out, 256)
        assert np.all(paused_out == 0)  # silence
        assert player._position == 256  # held

        player.resume()
        callback(indata, outdata, 256)
        assert player._position == 512  # advanced again

    @pytest.mark.unit
    def test_callback_captures_input_when_enabled(self) -> None:
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())
        samples = _audio(512).samples.reshape(-1, 1)
        callback = player._build_callback(samples, _CallbackStop, capture=True)

        indata = np.full((256, 1), _MIC_MARK, dtype=np.int16)
        callback(indata, np.zeros((256, 1), dtype=np.int16), 256)

        assert not player._input_queue.empty()  # input was queued

    @pytest.mark.unit
    def test_callback_stops_at_end_of_audio(self) -> None:
        player = DuplexAudioPlayer(blocksize=256, backend=_backend())
        samples = _audio(300).samples.reshape(-1, 1)
        callback = player._build_callback(samples, _CallbackStop, capture=False)

        indata = np.zeros((256, 1), dtype=np.int16)
        callback(indata, np.zeros((256, 1), dtype=np.int16), 256)
        outdata = np.ones((256, 1), dtype=np.int16)
        with pytest.raises(_CallbackStop):
            callback(indata, outdata, 256)
        assert np.all(outdata[44:] == 0)  # zero-padded past sample 300

    @pytest.mark.unit
    def test_pause_flag_reflects_state(self) -> None:
        player = DuplexAudioPlayer()
        assert player.is_paused is False
        player.pause()
        assert player.is_paused is True
        player.resume()
        assert player.is_paused is False

    @pytest.mark.unit
    def test_stop_without_active_stream_is_safe(self) -> None:
        DuplexAudioPlayer().stop()  # must not raise

    @pytest.mark.unit
    def test_stop_tolerates_a_closing_stream(self) -> None:
        class _AngryStream:
            def abort(self) -> None:
                raise RuntimeError("stream already closed")

        player = DuplexAudioPlayer()
        player._stream = _AngryStream()
        player.stop()  # must not raise


class TestDuplexConsume:
    """The input-consumption step in isolation."""

    @pytest.mark.unit
    def test_consume_once_without_callback_waits(self) -> None:
        player = DuplexAudioPlayer()
        player._finished.set()  # so the wait returns immediately
        player._consume_once(None)  # must not raise or deliver anything

    @pytest.mark.unit
    def test_consume_once_delivers_a_queued_frame(self) -> None:
        player = DuplexAudioPlayer()
        player._input_queue.put_nowait(b"frame")
        received: list[bytes] = []
        player._consume_once(received.append)
        assert received == [b"frame"]

    @pytest.mark.unit
    def test_consume_once_returns_when_queue_empty(self) -> None:
        player = DuplexAudioPlayer()
        received: list[bytes] = []
        player._consume_once(received.append)  # empty queue -> times out, no delivery
        assert received == []

    @pytest.mark.unit
    def test_drain_input_clears_stale_frames(self) -> None:
        player = DuplexAudioPlayer()
        player._input_queue.put_nowait(b"a")
        player._input_queue.put_nowait(b"b")
        player._drain_input()
        assert player._input_queue.empty()


class TestDuplexBackendResolver:
    """The lazy sounddevice duplex backend."""

    @pytest.mark.unit
    def test_missing_sounddevice_raises_audio_device_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "sounddevice":
                raise ImportError("no sounddevice")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        with pytest.raises(AudioDeviceError):
            _sounddevice_duplex_backend()

    @pytest.mark.unit
    def test_builds_backend_from_sounddevice(self) -> None:
        backend = _sounddevice_duplex_backend()
        assert backend.open_stream.__name__ == "Stream"
        assert issubclass(backend.callback_stop, Exception)
