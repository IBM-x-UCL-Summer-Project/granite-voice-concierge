# Standard library
from unittest.mock import MagicMock, patch

# Third-party
import pytest

# Local
from voice_concierge.voice_input import build_voice_input_pipeline


class TestBuildVoiceInputPipeline:
    """Unit tests for the build_voice_input_pipeline factory."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.factory.VoiceInputPipeline")
    @patch("voice_concierge.voice_input.factory.VoiceActivityDetector")
    @patch("voice_concierge.voice_input.factory.WakeWordDetector")
    def test_builds_default_detectors(
        self,
        mock_wake_word: MagicMock,
        mock_vad: MagicMock,
        mock_pipeline: MagicMock,
    ) -> None:
        """The factory builds default detectors and wires them into a pipeline."""
        pipeline = build_voice_input_pipeline()

        mock_wake_word.assert_called_once_with(audio_source=None)
        mock_vad.assert_called_once_with(audio_source=None)
        mock_pipeline.assert_called_once_with(
            wake_word_detector=mock_wake_word.return_value,
            voice_activity_detector=mock_vad.return_value,
        )
        assert pipeline is mock_pipeline.return_value

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.factory.VoiceInputPipeline")
    @patch("voice_concierge.voice_input.factory.VoiceActivityDetector")
    @patch("voice_concierge.voice_input.factory.WakeWordDetector")
    def test_uses_injected_detectors(
        self,
        mock_wake_word: MagicMock,
        mock_vad: MagicMock,
        mock_pipeline: MagicMock,
    ) -> None:
        """Injected detectors are wired directly without building defaults."""
        wake_word = MagicMock()
        vad = MagicMock()

        build_voice_input_pipeline(
            wake_word_detector=wake_word, voice_activity_detector=vad
        )

        mock_wake_word.assert_not_called()
        mock_vad.assert_not_called()
        mock_pipeline.assert_called_once_with(
            wake_word_detector=wake_word,
            voice_activity_detector=vad,
        )

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.factory.VoiceInputPipeline")
    @patch("voice_concierge.voice_input.factory.VoiceActivityDetector")
    @patch("voice_concierge.voice_input.factory.WakeWordDetector")
    def test_forwards_audio_source_to_detectors(
        self,
        mock_wake_word: MagicMock,
        mock_vad: MagicMock,
        mock_pipeline: MagicMock,
    ) -> None:
        """A supplied audio source is forwarded to both default detectors."""
        source = MagicMock()

        build_voice_input_pipeline(audio_source=source)

        mock_wake_word.assert_called_once_with(audio_source=source)
        mock_vad.assert_called_once_with(audio_source=source)
