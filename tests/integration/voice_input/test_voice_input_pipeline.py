# Standard library
from unittest.mock import MagicMock

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.voice_input import (
    VoiceActivityDetector,
    VoiceInputPipeline,
    WakeWordDetector,
)


class TestVoiceInputPipelineIntegration:
    """
    Integration tests for VoiceInputPipeline.

    These tests verify the pipeline correctly orchestrates WakeWordDetector
    and VoiceActivityDetector using mocked instances to avoid hardware
    dependencies while testing real pipeline wiring.
    """

    @pytest.mark.integration
    def test_wake_word_triggers_vad(self) -> None:
        """
        VoiceInputPipeline correctly hands off from wake word detection to VAD.
        Verifies the pipeline wiring between WakeWordDetector and
        VoiceActivityDetector works end to end.
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)

        # Simulate wake word firing then KeyboardInterrupt to stop the loop
        def listen_side_effect(on_wake_word):
            on_wake_word()
            raise KeyboardInterrupt

        mock_detector.listen.side_effect = listen_side_effect

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )
        callback = MagicMock()

        # Act
        pipeline.run(on_utterance_captured=callback)

        # Assert
        mock_vad.capture_utterance.assert_called_once_with(
            on_utterance_captured=pipeline._handle_utterance
        )

    @pytest.mark.integration
    def test_utterance_passed_to_callback(self) -> None:
        """
        VoiceInputPipeline passes captured utterance to the registered callback.
        Verifies the full pipeline: wake word -> VAD -> callback.
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)
        test_audio = np.zeros(1280, dtype=np.int16)

        def listen_side_effect(on_wake_word):
            on_wake_word()
            raise KeyboardInterrupt

        def capture_side_effect(on_utterance_captured):
            on_utterance_captured(test_audio)

        mock_detector.listen.side_effect = listen_side_effect
        mock_vad.capture_utterance.side_effect = capture_side_effect

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )
        callback = MagicMock()

        # Act
        pipeline.run(on_utterance_captured=callback)

        # Assert
        callback.assert_called_once_with(test_audio)

    @pytest.mark.integration
    def test_pipeline_loops_after_utterance_captured(self) -> None:
        """
        VoiceInputPipeline returns to wake word listening after each utterance.
        Verifies the pipeline resets and continues listening after capturing
        an utterance.
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)
        call_count = {"n": 0}

        def listen_side_effect(on_wake_word):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                raise KeyboardInterrupt
            on_wake_word()

        mock_detector.listen.side_effect = listen_side_effect

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act
        pipeline.run(on_utterance_captured=MagicMock())

        # Assert — listen() called 3 times before KeyboardInterrupt
        assert mock_detector.listen.call_count == 3

    @pytest.mark.integration
    def test_pipeline_uses_default_detectors_when_none_provided(self) -> None:
        """
        VoiceInputPipeline creates real WakeWordDetector and VoiceActivityDetector
        instances when none are provided.
        """
        # Arrange
        pipeline = VoiceInputPipeline()

        # Assert
        assert isinstance(pipeline._wake_word_detector, WakeWordDetector)
        assert isinstance(pipeline._voice_activity_detector, VoiceActivityDetector)

    @pytest.mark.integration
    def test_pipeline_stops_cleanly_on_keyboard_interrupt(self) -> None:
        """
        VoiceInputPipeline exits cleanly when KeyboardInterrupt is raised.
        Verifies no exceptions propagate out of run().
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)
        mock_detector.listen.side_effect = KeyboardInterrupt

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Act / Assert — should not raise
        pipeline.run(on_utterance_captured=MagicMock())

    @pytest.mark.integration
    def test_callback_receives_numpy_array(self) -> None:
        """
        VoiceInputPipeline passes a numpy int16 array to the callback.
        Verifies audio format is correct for downstream STT processing.
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)
        test_audio = np.zeros(1280, dtype=np.int16)

        def listen_side_effect(on_wake_word):
            on_wake_word()
            raise KeyboardInterrupt

        def capture_side_effect(on_utterance_captured):
            on_utterance_captured(test_audio)

        mock_detector.listen.side_effect = listen_side_effect
        mock_vad.capture_utterance.side_effect = capture_side_effect

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )
        callback = MagicMock()

        # Act
        pipeline.run(on_utterance_captured=callback)

        # Assert
        args, _ = callback.call_args
        assert isinstance(args[0], np.ndarray)
        assert args[0].dtype == np.int16

    @pytest.mark.integration
    def test_no_callback_registered_prints_placeholder(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """
        VoiceInputPipeline prints placeholder when no STT callback is connected.
        Verifies graceful handling when utterance is captured without a callback.
        """
        # Arrange
        mock_detector = MagicMock(spec=WakeWordDetector)
        mock_vad = MagicMock(spec=VoiceActivityDetector)
        test_audio = np.zeros(1280, dtype=np.int16)

        def listen_side_effect(on_wake_word):
            on_wake_word()
            raise KeyboardInterrupt

        def capture_side_effect(on_utterance_captured):
            on_utterance_captured(test_audio)

        mock_detector.listen.side_effect = listen_side_effect
        mock_vad.capture_utterance.side_effect = capture_side_effect

        pipeline = VoiceInputPipeline(
            wake_word_detector=mock_detector,
            voice_activity_detector=mock_vad,
        )

        # Manually set callback to None to simulate no STT connected
        pipeline._on_utterance_captured = None

        # Act
        pipeline.run(on_utterance_captured=None)

        # Assert
        captured = capsys.readouterr()
        assert "STT not connected" in captured.out
