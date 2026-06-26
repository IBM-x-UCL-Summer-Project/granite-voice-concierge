# Standard library
from collections import defaultdict, deque
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.voice_input import WakeWordDetector


class TestWakeWordDetectorInit:
    """Unit tests for WakeWordDetector initialisation."""

    @pytest.mark.unit
    def test_default_initialisation(self) -> None:
        """WakeWordDetector initialises with default values."""
        detector = WakeWordDetector(download_models=False)
        assert detector._confidence_threshold == 0.3
        assert detector._chunk == 1280
        assert detector._rate == 16000
        assert detector._channels == 1

    @pytest.mark.unit
    def test_custom_confidence_threshold(self) -> None:
        """WakeWordDetector accepts a custom confidence threshold."""
        detector = WakeWordDetector(confidence_threshold=0.7, download_models=False)
        assert detector._confidence_threshold == 0.7

    @pytest.mark.unit
    def test_custom_chunk_size(self) -> None:
        """WakeWordDetector accepts a custom chunk size."""
        detector = WakeWordDetector(chunk=2560, download_models=False)
        assert detector._chunk == 2560

    @pytest.mark.unit
    def test_model_is_loaded_on_init(self) -> None:
        """WakeWordDetector loads the openWakeWord model on initialisation."""
        detector = WakeWordDetector(download_models=False)
        assert detector._model is not None

    @pytest.mark.unit
    def test_custom_model_name(self) -> None:
        """WakeWordDetector accepts a custom model name."""
        detector = WakeWordDetector(
            model_name="hey_jarvis_v0.1.onnx", download_models=False
        )
        assert detector._model is not None


class TestWakeWordDetectorListen:
    """Unit tests for WakeWordDetector.listen()."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_listen_opens_audio_stream(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """listen() opens a PyAudio stream with correct parameters."""
        # Arrange — use KeyboardInterrupt to stop the loop immediately
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(download_models=False)
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        mock_pyaudio_instance.open.assert_called_once_with(
            format=detector._fmt,
            channels=detector._channels,
            rate=detector._rate,
            input=True,
            frames_per_buffer=detector._chunk,
        )

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_listen_cleans_up_stream_on_keyboard_interrupt(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """listen() closes the stream and terminates PyAudio on KeyboardInterrupt."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = KeyboardInterrupt
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(download_models=False)
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pyaudio_instance.terminate.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_listen_callback_not_called_on_silence(
        self, mock_pyaudio: MagicMock, silent_audio_stream: list[np.ndarray]
    ) -> None:
        """listen() does not fire callback when audio is silent."""
        # Arrange
        chunks = [chunk.tobytes() for chunk in silent_audio_stream]

        mock_stream = MagicMock()
        mock_stream.read.side_effect = chunks + [KeyboardInterrupt]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(download_models=False)
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_listen_resets_model_after_detection(self, mock_pyaudio: MagicMock) -> None:
        """listen() resets the model buffer after wake word is detected."""
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.return_value = np.zeros(1280, dtype=np.int16).tobytes()
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(download_models=False)

        # Mock predict() to avoid overwriting the injected buffer
        detector._model.predict = MagicMock()
        detector._model.prediction_buffer = defaultdict(
            deque, {"hey_jarvis_v0.1.onnx": deque([0.9])}
        )
        detector._model.reset = MagicMock()
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        detector._model.reset.assert_called_once()
