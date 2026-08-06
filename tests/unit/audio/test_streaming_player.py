# Standard library
import threading
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.player import AudioPlayer
from voice_concierge.audio.streaming_player import (
    PlaybackBackend,
    StreamingAudioPlayer,
    _sounddevice_backend,
)


class _CallbackStop(Exception):
    """Stand-in for sounddevice.CallbackStop."""


class _FakeStream:
    """Output stream that pulls blocks on a thread, like PortAudio does."""

    def __init__(self, *, callback, finished_callback, blocksize, channels, **_):
        self._callback = callback
        self._finished_callback = finished_callback
        self._blocksize = blocksize
        self._channels = channels
        self.blocks: list[np.ndarray] = []
        self.aborted = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_FakeStream":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            outdata = np.zeros((self._blocksize, self._channels), dtype=np.int16)
            try:
                self._callback(outdata, self._blocksize, None, None)
            except _CallbackStop:
                self.blocks.append(outdata.copy())
                break
            self.blocks.append(outdata.copy())
        self._finished_callback()

    def abort(self) -> None:
        self.aborted = True
        self._stop.set()


def _audio(num_samples: int = 4096) -> CapturedAudio:
    ramp = np.arange(1, num_samples + 1, dtype=np.int16)
    return CapturedAudio(samples=ramp, sample_rate=16000, channels=1)


def _backend(stream_cls=_FakeStream) -> PlaybackBackend:
    return PlaybackBackend(open_stream=stream_cls, callback_stop=_CallbackStop)


class TestStreamingAudioPlayerPlayback:
    """Unit tests for straight-through playback."""

    @pytest.mark.unit
    def test_plays_all_samples_then_returns(self) -> None:
        """play() emits every sample in order and blocks until finished."""
        player = StreamingAudioPlayer(blocksize=512, backend=_backend())
        audio = _audio(2048)

        player.play(audio)

        assert player._stream is None  # released after playback

    @pytest.mark.unit
    def test_satisfies_audio_player_protocol(self) -> None:
        """StreamingAudioPlayer satisfies the AudioPlayer protocol."""
        assert isinstance(StreamingAudioPlayer(), AudioPlayer)

    @pytest.mark.unit
    def test_satisfies_playback_controller_protocol(self) -> None:
        """It also satisfies PlaybackController, without audio importing it."""
        from voice_concierge.command_control import PlaybackController

        assert isinstance(StreamingAudioPlayer(), PlaybackController)

    @pytest.mark.unit
    def test_wraps_backend_failure(self) -> None:
        """A failure opening the stream surfaces as AudioDeviceError."""

        def _explode(**_):
            raise RuntimeError("no output device")

        player = StreamingAudioPlayer(backend=_backend(stream_cls=_explode))

        with pytest.raises(AudioDeviceError):
            player.play(_audio(64))

    @pytest.mark.unit
    @patch("voice_concierge.audio.streaming_player._sounddevice_backend")
    def test_uses_sounddevice_backend_by_default(self, mock_backend: patch) -> None:
        """Without an injected backend, the sounddevice backend is resolved."""
        mock_backend.return_value = _backend()

        StreamingAudioPlayer(blocksize=512).play(_audio(512))

        mock_backend.assert_called_once_with()


class TestStreamingAudioPlayerControl:
    """Unit tests for stop, pause, and resume."""

    @pytest.mark.unit
    def test_pause_emits_silence_and_holds_position(self) -> None:
        """While paused the callback emits silence and does not advance."""
        player = StreamingAudioPlayer(blocksize=256, backend=_backend())
        samples = _audio(4096).samples.reshape(-1, 1)
        callback = player._build_callback(samples, _CallbackStop)

        outdata = np.zeros((256, 1), dtype=np.int16)
        callback(outdata, 256)
        assert player._position == 256

        player.pause()
        assert player.is_paused
        paused_out = np.ones((256, 1), dtype=np.int16)
        callback(paused_out, 256)

        assert np.all(paused_out == 0)  # silence
        assert player._position == 256  # position held

        player.resume()
        assert not player.is_paused
        callback(outdata, 256)
        assert player._position == 512  # advanced again

    @pytest.mark.unit
    def test_callback_stops_at_end_of_audio(self) -> None:
        """The final short block is zero-padded and ends the stream."""
        player = StreamingAudioPlayer(blocksize=256, backend=_backend())
        samples = _audio(300).samples.reshape(-1, 1)
        callback = player._build_callback(samples, _CallbackStop)

        callback(np.zeros((256, 1), dtype=np.int16), 256)
        outdata = np.ones((256, 1), dtype=np.int16)

        with pytest.raises(_CallbackStop):
            callback(outdata, 256)

        assert np.all(outdata[44:] == 0)  # padded past the 300th sample

    @pytest.mark.unit
    def test_stop_aborts_the_stream_and_unblocks_play(self) -> None:
        """stop() from another thread aborts the stream and returns play()."""
        player = StreamingAudioPlayer(blocksize=256, backend=_backend())
        streams: list[_FakeStream] = []

        original = _FakeStream.__enter__

        def _capture(self):
            streams.append(self)
            return original(self)

        with patch.object(_FakeStream, "__enter__", _capture):
            stopper = threading.Thread(target=_stop_when_started(player, streams))
            stopper.start()
            player.play(_audio(16_000_000))  # long enough to require stopping
            stopper.join(timeout=2.0)

        assert streams[0].aborted
        assert player._stream is None

    @pytest.mark.unit
    def test_stop_without_active_stream_is_safe(self) -> None:
        """stop() before any playback does nothing."""
        StreamingAudioPlayer().stop()  # must not raise

    @pytest.mark.unit
    def test_stop_tolerates_a_closing_stream(self) -> None:
        """An abort() that raises because the stream is closing is ignored."""

        class _AngryStream:
            def abort(self) -> None:
                raise RuntimeError("stream already closed")

        player = StreamingAudioPlayer()
        player._stream = _AngryStream()

        player.stop()  # must not raise

    @pytest.mark.unit
    def test_pause_is_cleared_between_plays(self) -> None:
        """A play() left paused does not start the next one paused."""
        player = StreamingAudioPlayer(blocksize=256, backend=_backend())
        player.pause()

        player.play(_audio(512))

        assert not player.is_paused


def _stop_when_started(player: StreamingAudioPlayer, streams: list) -> object:
    """Return a target that stops the player once its stream is running."""

    def _target() -> None:
        for _ in range(200):
            if streams and player._position > 0:
                player.stop()
                return
            threading.Event().wait(0.01)

    return _target


class TestSoundDeviceBackend:
    """Unit tests for the lazy sounddevice backend resolver."""

    @pytest.mark.unit
    def test_missing_sounddevice_raises_audio_device_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing sounddevice dependency surfaces as AudioDeviceError."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "sounddevice":
                raise ImportError("no sounddevice")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(AudioDeviceError):
            _sounddevice_backend()

    @pytest.mark.unit
    def test_builds_backend_from_sounddevice(self) -> None:
        """The backend exposes sounddevice's stream type and stop exception."""
        backend = _sounddevice_backend()

        assert backend.open_stream.__name__ == "OutputStream"
        assert issubclass(backend.callback_stop, Exception)
