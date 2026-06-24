# Standard library
from unittest.mock import MagicMock, patch, call
import time

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.voice_input import VoiceActivityDetector


class TestVoiceActivityDetectorInit:
    """Unit tests for VoiceActivityDetector initialisation."""

    @pytest.mark.unit
    def test_default_initialisation(self) -> None:
        """VoiceActivityDetector initialises with default values."""
        vad = VoiceActivityDetector()
        assert vad._confidence_threshold == 0.5
        assert vad._min_silence_ms == 500
        assert vad._padding_ms == 100
        assert vad._max_wait_s == 5
        assert vad._chunk == 512
        assert vad._rate == 16000
        assert vad._channels == 1
        assert vad._collect_metrics is False

    @pytest.mark.unit
    def test_custom_confidence_threshold(self) -> None:
        """VoiceActivityDetector accepts a custom confidence threshold."""
        vad = VoiceActivityDetector(confidence_threshold=0.7)
        assert vad._confidence_threshold == 0.7

    @pytest.mark.unit
    def test_custom_min_silence_ms(self) -> None:
        """VoiceActivityDetector accepts a custom min silence duration."""
        vad = VoiceActivityDetector(min_silence_ms=500)
        assert vad._min_silence_ms == 500

    @pytest.mark.unit
    def test_custom_max_wait_s(self) -> None:
        """VoiceActivityDetector accepts a custom max wait duration."""
        vad = VoiceActivityDetector(max_wait_s=10)
        assert vad._max_wait_s == 10

    @pytest.mark.unit
    def test_collect_metrics_disabled_by_default(self) -> None:
        """VoiceActivityDetector has metrics collection disabled by default."""
        vad = VoiceActivityDetector()
        assert vad._collect_metrics is False

    @pytest.mark.unit
    def test_collect_metrics_can_be_enabled(self) -> None:
        """VoiceActivityDetector can enable metrics collection."""
        vad = VoiceActivityDetector(collect_metrics=True)
        assert vad._collect_metrics is True

    @pytest.mark.unit
    def test_vad_model_is_loaded_on_init(self) -> None:
        """VoiceActivityDetector loads the Silero VAD model on initialisation."""
        vad = VoiceActivityDetector()
        assert vad._vad_model is not None

    @pytest.mark.unit
    def test_vad_iterator_is_created_on_init(self) -> None:
        """VoiceActivityDetector creates a VADIterator on initialisation."""
        vad = VoiceActivityDetector()
        assert vad._vad_iterator is not None


class TestVoiceActivityDetectorCaptureUtterance:
    """Unit tests for VoiceActivityDetector.capture_utterance()."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_opens_audio_stream(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() opens a PyAudio stream with correct parameters."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector()
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        mock_pyaudio_instance.open.assert_called_once_with(
            format=vad._fmt,
            channels=vad._channels,
            rate=vad._rate,
            input=True,
            frames_per_buffer=vad._chunk,
        )

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_cleans_up_on_keyboard_interrupt(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() closes stream and terminates PyAudio on KeyboardInterrupt."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector()
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pyaudio_instance.terminate.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_times_out_when_no_speech(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() exits cleanly when no speech is detected within timeout."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.return_value = np.zeros(512, dtype=np.int16).tobytes()
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector(max_wait_s=1)
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert — callback should not be called on timeout
        callback.assert_not_called()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_callback_called_on_speech_end(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() calls callback when speech end is detected."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.return_value = np.zeros(512, dtype=np.int16).tobytes()
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector()

        # Mock VAD iterator to simulate speech start then end
        vad._vad_iterator = MagicMock()
        vad._vad_iterator.side_effect = [
            {"start": 0},   # first chunk — speech starts
            {"end": 512},   # second chunk — speech ends
        ]

        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        callback.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_callback_receives_numpy_array(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() passes a numpy array to the callback."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.return_value = np.zeros(512, dtype=np.int16).tobytes()
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector()
        vad._vad_iterator = MagicMock()
        vad._vad_iterator.side_effect = [
            {"start": 0},
            {"end": 512},
        ]

        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        args, _ = callback.call_args
        assert isinstance(args[0], np.ndarray)
        assert args[0].dtype == np.int16

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    def test_capture_utterance_does_not_collect_metrics_by_default(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() does not collect metrics when collect_metrics=False."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        vad = VoiceActivityDetector(collect_metrics=False)
        vad._collect_perf_metrics = MagicMock()
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        vad._collect_perf_metrics.assert_not_called()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    @patch("voice_concierge.voice_input.voice_activity_detector.tracemalloc")
    def test_capture_utterance_handles_tracemalloc_already_stopped(
        self, mock_tracemalloc: MagicMock, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() handles case where tracemalloc is already stopped."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.return_value = np.zeros(512, dtype=np.int16).tobytes()
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        # Simulate tracemalloc not tracing
        mock_tracemalloc.is_tracing.return_value = False
        mock_tracemalloc.get_traced_memory.return_value = (0, 0)

        vad = VoiceActivityDetector(collect_metrics=True)
        vad._vad_iterator = MagicMock()
        vad._vad_iterator.side_effect = [
            {"start": 0},
            {"end": 512},
        ]
        callback = MagicMock()

        # Act / Assert — should not raise even when tracemalloc is not tracing
        vad.capture_utterance(on_utterance_captured=callback)
        mock_tracemalloc.stop.assert_not_called()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.pyaudio.PyAudio")
    @patch("voice_concierge.voice_input.voice_activity_detector.tracemalloc")
    def test_capture_utterance_stops_tracemalloc_on_keyboard_interrupt(
        self, mock_tracemalloc: MagicMock, mock_pyaudio: MagicMock
    ) -> None:
        """capture_utterance() stops tracemalloc in finally block on KeyboardInterrupt."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        # Simulate tracemalloc still tracing when finally block runs
        mock_tracemalloc.is_tracing.return_value = True
        mock_tracemalloc.get_traced_memory.return_value = (0, 0)

        vad = VoiceActivityDetector(collect_metrics=True)
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert — tracemalloc.stop() called in finally block
        mock_tracemalloc.stop.assert_called_once()
