# Standard library
from unittest.mock import MagicMock

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio, FakeAudioSource
from voice_concierge.voice_input import VoiceActivityDetector

_CHUNK = np.zeros(512, dtype=np.int16).tobytes()


class TestVoiceActivityDetectorIntegration:
    """
    Integration tests for VoiceActivityDetector.

    These tests use the real Silero VAD model but feed audio through a
    FakeAudioSource to avoid requiring a physical microphone. Audio is
    simulated using numpy arrays.
    """

    @pytest.mark.integration
    def test_silent_audio_does_not_trigger_callback(self) -> None:
        """
        VoiceActivityDetector does not trigger callback on silent audio.
        Verifies the real Silero VAD model does not produce false positives
        on silence within the timeout window.
        """
        # Arrange
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(max_wait_s=1, audio_source=source)
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        callback.assert_not_called()

    @pytest.mark.integration
    def test_speech_start_and_end_triggers_callback(self) -> None:
        """
        VoiceActivityDetector triggers callback when real VAD detects speech
        start and end events.
        """
        # Arrange
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        callback.assert_called_once()

    @pytest.mark.integration
    def test_callback_receives_captured_audio(self) -> None:
        """
        VoiceActivityDetector passes a CapturedAudio to the callback.
        Verifies audio format is correct for downstream STT processing.
        """
        # Arrange
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        (audio,), _ = callback.call_args
        assert isinstance(audio, CapturedAudio)
        assert audio.samples.dtype == np.int16

    @pytest.mark.integration
    def test_timeout_closes_source(self) -> None:
        """
        VoiceActivityDetector closes the audio source cleanly on timeout.
        """
        # Arrange
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(max_wait_s=1, audio_source=source)
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        assert source.close_count >= 1

    @pytest.mark.integration
    def test_metrics_collected_when_enabled(self) -> None:
        """
        VoiceActivityDetector collects and prints metrics when collect_metrics=True.
        Verifies metrics collection integrates correctly with utterance capture.
        """
        # Arrange
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(collect_metrics=True, audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        vad._collect_perf_metrics = MagicMock(
            return_value={
                "latency_ms": 100.0,
                "ram_current_mb": 0.1,
                "ram_peak_mb": 0.2,
                "ram_system_mb": 200.0,
                "cpu_percent": 8.0,
                "samples": 512,
            }
        )
        vad._print_metrics = MagicMock()
        callback = MagicMock()

        # Act
        vad.capture_utterance(on_utterance_captured=callback)

        # Assert
        vad._collect_perf_metrics.assert_called_once()
        vad._print_metrics.assert_called_once()
