# Standard library
from unittest.mock import MagicMock, patch, call

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.voice_input import VoiceInputPipeline
from voice_concierge.voice_input import WakeWordDetector
from voice_concierge.voice_input import VoiceActivityDetector


class TestVoiceInputPipelineInit:
    """Unit tests for VoiceInputPipeline initialisation."""

    @pytest.mark.unit
    def test_default_initialisation(self) -> None:
        """VoiceInputPipeline creates default detector instances when none provided."""
        pipeline = VoiceInputPipeline()
        assert isinstance(pipeline._wake_word_detector, WakeWordDetector)
        assert isinstance(pipeline._voice_activity_detector, VoiceActivityDetector)

    @pytest.mark.unit
    def test_custom_wake_word_detector(self) -> None:
        """VoiceInputPipeline accepts a custom WakeWordDetector instance."""
        custom_detector = MagicMock(spec=WakeWordDetector)
        pipeline = VoiceInputPipeline(wake_word_detector=custom_detector)
        assert pipeline._wake_word_detector is custom_detector

    @pytest.mark.unit
    def test_custom_voice_activity_detector(self) -> None:
        """VoiceInputPipeline accepts a custom VoiceActivityDetector instance."""
        custom_vad = MagicMock(spec=VoiceActivityDetector)
        pipeline = VoiceInputPipeline(voice_activity_detector=custom_vad)
        assert pipeline._voice_activity_detector is custom_vad

    @pytest.mark.unit
    def test_on_utterance_captured_is_none_before_run(self) -> None:
        """VoiceInputPipeline has no utterance callback before run() is called."""
        pipeline = VoiceInputPipeline()
        assert pipeline._on_utterance_captured is None


class TestVoiceInputPipelineRun:
    """Unit tests for VoiceInputPipeline.run()."""

    @pytest.mark.unit
    def test_run_sets_utterance_callback(self) -> None:
        """run() registers the provided callback before starting the pipeline."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_detector.listen.side_effect = KeyboardInterrupt
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )
        callback = MagicMock()

        # Act
        pipeline.run(on_utterance_captured=callback)

        # Assert
        assert pipeline._on_utterance_captured is callback

    @pytest.mark.unit
    def test_run_starts_wake_word_detector(self) -> None:
        """run() calls listen() on the wake word detector."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_detector.listen.side_effect = KeyboardInterrupt
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act
        pipeline.run(on_utterance_captured=MagicMock())

        # Assert
        mock_detector.listen.assert_called_once()

    @pytest.mark.unit
    def test_run_passes_wake_word_callback_to_detector(self) -> None:
        """run() passes _on_wake_word as the callback to the wake word detector."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_detector.listen.side_effect = KeyboardInterrupt
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act
        pipeline.run(on_utterance_captured=MagicMock())

        # Assert
        mock_detector.listen.assert_called_once_with(
            on_wake_word=pipeline._on_wake_word
        )

    @pytest.mark.unit
    def test_run_stops_cleanly_on_keyboard_interrupt(self) -> None:
        """run() exits cleanly when KeyboardInterrupt is raised."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_detector.listen.side_effect = KeyboardInterrupt
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act / Assert — should not raise
        pipeline.run(on_utterance_captured=MagicMock())


class TestVoiceInputPipelineWakeWordCallback:
    """Unit tests for VoiceInputPipeline._on_wake_word()."""

    @pytest.mark.unit
    def test_on_wake_word_triggers_vad(self) -> None:
        """_on_wake_word() calls capture_utterance() on the VAD."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act
        pipeline._on_wake_word()

        # Assert
        mock_vad.capture_utterance.assert_called_once()

    @pytest.mark.unit
    def test_on_wake_word_passes_handle_utterance_as_callback(self) -> None:
        """_on_wake_word() passes _handle_utterance as the VAD callback."""
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act
        pipeline._on_wake_word()

        # Assert
        mock_vad.capture_utterance.assert_called_once_with(
            on_utterance_captured=pipeline._handle_utterance
        )


class TestVoiceInputPipelineHandleUtterance:
    """Unit tests for VoiceInputPipeline._handle_utterance()."""

    @pytest.mark.unit
    def test_handle_utterance_calls_registered_callback(self) -> None:
        """_handle_utterance() passes audio to the registered callback."""
        # Arrange
        pipeline = VoiceInputPipeline()
        callback = MagicMock()
        pipeline._on_utterance_captured = callback
        audio = np.zeros(1280, dtype=np.int16)

        # Act
        pipeline._handle_utterance(audio)

        # Assert
        callback.assert_called_once_with(audio)

    @pytest.mark.unit
    def test_handle_utterance_prints_placeholder_when_no_callback(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """_handle_utterance() prints placeholder when no callback is registered."""
        # Arrange
        pipeline = VoiceInputPipeline()
        pipeline._on_utterance_captured = None
        audio = np.zeros(1280, dtype=np.int16)

        # Act
        pipeline._handle_utterance(audio)

        # Assert
        captured = capsys.readouterr()
        assert "STT not connected" in captured.out
