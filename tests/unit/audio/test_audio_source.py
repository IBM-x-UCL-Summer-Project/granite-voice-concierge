# Standard library
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import AudioDeviceError, AudioSource, FakeAudioSource
from voice_concierge.audio.source import PyAudioSource


class TestPyAudioSource:
    """Unit tests for the PyAudio-backed AudioSource."""

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_open_opens_stream_with_configured_params(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """open() opens a PyAudio input stream with the configured params."""
        mock_instance = MagicMock()
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource(rate=16000, channels=1, frames_per_buffer=512)
        source.open()

        mock_instance.open.assert_called_once_with(
            format=source._fmt,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=512,
        )

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_open_uses_configured_input_device_index(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """open() can target a specific PyAudio input device."""
        mock_instance = MagicMock()
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource(input_device_index=3)
        source.open()

        assert mock_instance.open.call_args.kwargs["input_device_index"] == 3

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_read_delegates_to_stream(self, mock_pyaudio: MagicMock) -> None:
        """read() reads from the stream without raising on overflow."""
        chunk = np.zeros(512, dtype=np.int16).tobytes()
        mock_stream = MagicMock()
        mock_stream.read.return_value = chunk
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource()
        source.open()
        result = source.read(512)

        assert result == chunk
        mock_stream.read.assert_called_once_with(512, exception_on_overflow=False)

    @pytest.mark.unit
    def test_read_before_open_raises(self) -> None:
        """read() before open() raises an AudioDeviceError."""
        source = PyAudioSource()

        with pytest.raises(AudioDeviceError):
            source.read(512)

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_close_stops_stream_and_terminates(self, mock_pyaudio: MagicMock) -> None:
        """close() stops/closes the stream and terminates PyAudio."""
        mock_stream = MagicMock()
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource()
        source.open()
        source.close()

        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_instance.terminate.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_open_failure_raises_audio_device_error(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """A failure opening the device is wrapped in AudioDeviceError."""
        mock_instance = MagicMock()
        mock_instance.open.side_effect = OSError("no device")
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource()

        with pytest.raises(AudioDeviceError):
            source.open()

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_context_manager_opens_and_closes(self, mock_pyaudio: MagicMock) -> None:
        """Using PyAudioSource as a context manager opens then closes it."""
        mock_stream = MagicMock()
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_instance

        with PyAudioSource() as source:
            assert source._stream is mock_stream

        mock_stream.close.assert_called_once()
        mock_instance.terminate.assert_called_once()

    @pytest.mark.unit
    def test_close_without_open_is_a_safe_noop(self) -> None:
        """close() before open() does nothing and leaves state cleared."""
        source = PyAudioSource()

        source.close()

        assert source._stream is None
        assert source._pyaudio is None

    @pytest.mark.unit
    @patch("voice_concierge.audio.source.pyaudio.PyAudio")
    def test_close_swallows_cleanup_errors(self, mock_pyaudio: MagicMock) -> None:
        """close() swallows errors during cleanup and still clears state."""
        mock_stream = MagicMock()
        mock_stream.stop_stream.side_effect = RuntimeError("boom")
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_instance

        source = PyAudioSource()
        source.open()
        source.close()

        assert source._stream is None
        assert source._pyaudio is None


class TestFakeAudioSource:
    """Unit tests for the in-memory FakeAudioSource."""

    @pytest.mark.unit
    def test_yields_queued_chunks_in_order(self) -> None:
        """read() returns queued chunks in FIFO order."""
        source = FakeAudioSource([b"a", b"b"])

        assert source.read(1) == b"a"
        assert source.read(1) == b"b"

    @pytest.mark.unit
    def test_repeats_fill_after_exhaustion(self) -> None:
        """read() repeats the fill chunk once the queue is exhausted."""
        source = FakeAudioSource([b"a"], fill=b"z")

        assert source.read(1) == b"a"
        assert source.read(1) == b"z"
        assert source.read(1) == b"z"

    @pytest.mark.unit
    def test_raises_configured_exception_when_exhausted(self) -> None:
        """read() raises the configured exception once exhausted."""
        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            source.read(1)

    @pytest.mark.unit
    def test_exhausted_without_fill_raises_audio_device_error(self) -> None:
        """read() raises AudioDeviceError when exhausted with no fill/exception."""
        source = FakeAudioSource()

        with pytest.raises(AudioDeviceError):
            source.read(1)

    @pytest.mark.unit
    def test_counts_open_and_close(self) -> None:
        """open()/close() increment their counters (via context manager)."""
        source = FakeAudioSource([b"a"])

        with source:
            pass

        assert source.open_count == 1
        assert source.close_count == 1

    @pytest.mark.unit
    def test_satisfies_audio_source_protocol(self) -> None:
        """Both implementations satisfy the runtime-checkable AudioSource."""
        assert isinstance(FakeAudioSource(), AudioSource)
        assert isinstance(PyAudioSource(), AudioSource)


@pytest.mark.unit
class TestReadAvailability:
    """Callers with a deadline need to know before committing to a read."""

    def test_a_closed_source_has_nothing_available(self) -> None:
        assert PyAudioSource().available() == 0

    def test_availability_is_reported_from_the_stream(self) -> None:
        source = PyAudioSource()
        source._stream = SimpleNamespace(get_read_available=lambda: 512)

        assert source.available() == 512

    def test_a_wedged_stream_reports_nothing_rather_than_raising(self) -> None:
        """A bad device must not turn a readiness check into a crash."""

        def _explode() -> int:
            raise OSError("device gone")

        source = PyAudioSource()
        source._stream = SimpleNamespace(get_read_available=_explode)

        assert source.available() == 0
