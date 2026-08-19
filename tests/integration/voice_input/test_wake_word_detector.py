# Standard library
from pathlib import Path
from unittest.mock import MagicMock

# Third-party
import numpy as np
import openwakeword
import pytest

# Local
from voice_concierge.audio import FakeAudioSource
from voice_concierge.voice_input import WakeWordDetector


def _has_default_openwakeword_model() -> bool:
    model_path = (
        Path(openwakeword.__file__).resolve().parent
        / "resources"
        / "models"
        / "hey_jarvis_v0.1.onnx"
    )
    return model_path.is_file()


pytestmark = pytest.mark.skipif(
    not _has_default_openwakeword_model(),
    reason="Requires downloaded openWakeWord model resources.",
)


class TestWakeWordDetectorIntegration:
    """
    Integration tests for WakeWordDetector.

    These tests use the real openWakeWord model but feed audio through a
    FakeAudioSource to avoid requiring a physical microphone. Audio is
    simulated using numpy arrays.
    """

    @pytest.mark.integration
    def test_detector_does_not_trigger_on_silence(
        self, silent_audio_stream: list[np.ndarray]
    ) -> None:
        """
        WakeWordDetector does not trigger callback when given silent audio.
        Verifies the real model does not produce false positives on silence.
        """
        # Arrange
        chunks = [chunk.tobytes() for chunk in silent_audio_stream]
        source = FakeAudioSource(chunks, raise_when_exhausted=KeyboardInterrupt())
        detector = WakeWordDetector(
            confidence_threshold=0.3, download_models=False, audio_source=source
        )
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    def test_detector_does_not_trigger_on_synthetic_tone(
        self, hey_jarvis_audio: np.ndarray
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
        source = FakeAudioSource(chunks, raise_when_exhausted=KeyboardInterrupt())
        detector = WakeWordDetector(
            confidence_threshold=0.3, download_models=False, audio_source=source
        )
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    def test_detector_triggers_callback_above_threshold(self) -> None:
        """
        WakeWordDetector triggers callback when model confidence exceeds threshold.
        Uses a real model with an injected high-confidence prediction buffer.
        """
        # Arrange
        source = FakeAudioSource(
            [np.zeros(1280, dtype=np.int16).tobytes()],
            raise_when_exhausted=KeyboardInterrupt(),
        )
        detector = WakeWordDetector(
            confidence_threshold=0.3, download_models=False, audio_source=source
        )
        detector._model.predict = MagicMock(return_value={"hey_jarvis_v0.1.onnx": 0.9})
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_called_once()

    @pytest.mark.integration
    def test_detector_does_not_trigger_below_threshold(self) -> None:
        """
        WakeWordDetector does not trigger callback when confidence is below threshold.
        Verifies the threshold is correctly applied against the real model buffer.
        """
        # Arrange
        source = FakeAudioSource(
            [np.zeros(1280, dtype=np.int16).tobytes()],
            raise_when_exhausted=KeyboardInterrupt(),
        )
        detector = WakeWordDetector(
            confidence_threshold=0.5, download_models=False, audio_source=source
        )
        detector._model.predict = MagicMock(return_value={"hey_jarvis_v0.1.onnx": 0.3})
        callback = MagicMock()

        # Act
        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    def test_detector_resets_after_detection(self) -> None:
        """
        WakeWordDetector resets the model buffer after each detection.
        Verifies the real model reset method is called to prevent repeat triggers.
        """
        # Arrange
        source = FakeAudioSource(
            [np.zeros(1280, dtype=np.int16).tobytes()],
            raise_when_exhausted=KeyboardInterrupt(),
        )
        detector = WakeWordDetector(
            confidence_threshold=0.3, download_models=False, audio_source=source
        )
        detector._model.predict = MagicMock(return_value={"hey_jarvis_v0.1.onnx": 0.9})
        original_reset = detector._model.reset
        detector._model.reset = MagicMock(side_effect=original_reset)
        callback = MagicMock()

        # Act
        detector.listen(on_wake_word=callback)

        # Assert
        detector._model.reset.assert_called_once()
