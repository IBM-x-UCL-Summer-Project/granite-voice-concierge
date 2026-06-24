# Standard library
from collections import defaultdict, deque
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.voice_input import WakeWordDetector


class TestWakeWordDetectorIntegration:
    """
    Integration tests for WakeWordDetector.

    These tests use the real openWakeWord model but mock PyAudio to avoid
    requiring a physical microphone. Audio is simulated using numpy arrays.
    """

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_does_not_trigger_on_silence(
        self, mock_pyaudio: MagicMock, silent_audio_stream: list[np.ndarray]
    ) -> None:
        """
        WakeWordDetector does not trigger callback when given silent audio.
        Verifies the real model does not produce false positives on silence.
        """
        # Arrange
        chunks = [chunk.tobytes() for chunk in silent_audio_stream]

        mock_stream = MagicMock()
        mock_stream.read.side_effect = chunks + [KeyboardInterrupt]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(confidence_threshold=0.3)
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_does_not_trigger_on_synthetic_tone(
        self, mock_pyaudio: MagicMock, hey_jarvis_audio: np.ndarray
    ) -> None:
        """
        WakeWordDetector does not trigger on a sine wave tone.
        Verifies the model distinguishes speech from arbitrary audio energy.
        """
        # Arrange
        chunk_size: int = 1280
        chunks = [
            hey_jarvis_audio[i : i + chunk_size].tobytes()
            for i in range(0, len(hey_jarvis_audio), chunk_size)
        ]

        mock_stream = MagicMock()
        mock_stream.read.side_effect = chunks + [KeyboardInterrupt]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(confidence_threshold=0.3)
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_triggers_callback_above_threshold(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """
        WakeWordDetector triggers callback when model confidence exceeds threshold.
        Uses a real model with an injected high-confidence prediction buffer.
        """
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = [
            np.zeros(1280, dtype=np.int16).tobytes(),
            KeyboardInterrupt,
        ]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(confidence_threshold=0.3)

        # Inject high confidence using real model buffer types
        detector._model.predict = MagicMock()
        detector._model.prediction_buffer = defaultdict(
            deque, {"hey_jarvis_v0.1.onnx": deque([0.9])}
        )
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_called_once()

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_does_not_trigger_below_threshold(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """
        WakeWordDetector does not trigger callback when confidence is below threshold.
        Verifies the threshold is correctly applied against the real model buffer.
        """
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = [
            np.zeros(1280, dtype=np.int16).tobytes(),
            KeyboardInterrupt,
        ]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(confidence_threshold=0.5)

        # Inject low confidence using real model buffer types
        detector._model.predict = MagicMock()
        detector._model.prediction_buffer = defaultdict(
            deque, {"hey_jarvis_v0.1.onnx": deque([0.3])}
        )
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_resets_after_detection(self, mock_pyaudio: MagicMock) -> None:
        """
        WakeWordDetector resets the model buffer after each detection.
        Verifies the real model reset method is called to prevent repeat triggers.
        """
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = [
            np.zeros(1280, dtype=np.int16).tobytes(),
            KeyboardInterrupt,
        ]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector(confidence_threshold=0.3)
        detector._model.predict = MagicMock()
        detector._model.prediction_buffer = defaultdict(
            deque, {"hey_jarvis_v0.1.onnx": deque([0.9])}
        )
        original_reset = detector._model.reset
        detector._model.reset = MagicMock(side_effect=original_reset)
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        detector._model.reset.assert_called_once()

    @pytest.mark.integration
    @patch("voice_concierge.voice_input.wake_word_detector.pyaudio.PyAudio")
    def test_detector_opens_stream_with_correct_audio_config(
        self, mock_pyaudio: MagicMock
    ) -> None:
        """
        WakeWordDetector opens PyAudio stream with correct audio configuration.
        Verifies rate, channels, chunk size match openWakeWord requirements.
        """
        # Arrange
        mock_stream = MagicMock()
        mock_stream.read.side_effect = [KeyboardInterrupt]
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.open.return_value = mock_stream
        mock_pyaudio.return_value = mock_pyaudio_instance

        detector = WakeWordDetector()

        # Act
        detector.listen(on_wake_word=MagicMock())

        # Assert
        mock_pyaudio_instance.open.assert_called_once_with(
            format=detector._fmt,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1280,
        )
