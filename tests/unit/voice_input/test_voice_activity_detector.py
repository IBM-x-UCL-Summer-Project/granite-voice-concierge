# Standard library
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio, FakeAudioSource, PyAudioSource
from voice_concierge.voice_input import VoiceActivityDetector

_CHUNK = np.zeros(512, dtype=np.int16).tobytes()


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
        vad = VoiceActivityDetector(min_silence_ms=300)
        assert vad._min_silence_ms == 300

    @pytest.mark.unit
    def test_custom_max_wait_s(self) -> None:
        """VoiceActivityDetector accepts a custom max wait duration."""
        vad = VoiceActivityDetector(max_wait_s=10)
        assert vad._max_wait_s == 10

    @pytest.mark.unit
    def test_collect_metrics_can_be_enabled(self) -> None:
        """VoiceActivityDetector can enable metrics collection."""
        vad = VoiceActivityDetector(collect_metrics=True)
        assert vad._collect_metrics is True

    @pytest.mark.unit
    def test_creates_default_pyaudio_source(self) -> None:
        """A default PyAudioSource is created when none is injected."""
        vad = VoiceActivityDetector()
        assert isinstance(vad._audio_source, PyAudioSource)

    @pytest.mark.unit
    def test_uses_injected_audio_source(self) -> None:
        """An injected audio source is used as-is."""
        source = FakeAudioSource()
        vad = VoiceActivityDetector(audio_source=source)
        assert vad._audio_source is source

    @pytest.mark.unit
    def test_vad_model_and_iterator_created_on_init(self) -> None:
        """VoiceActivityDetector loads the Silero VAD model and iterator."""
        vad = VoiceActivityDetector()
        assert vad._vad_model is not None
        assert vad._vad_iterator is not None


class TestVoiceActivityDetectorCaptureUtterance:
    """Unit tests for VoiceActivityDetector.capture_utterance()."""

    @pytest.mark.unit
    def test_opens_audio_source(self) -> None:
        """capture_utterance() opens the audio source before reading."""
        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())
        vad = VoiceActivityDetector(audio_source=source)

        with pytest.raises(KeyboardInterrupt):
            vad.capture_utterance(on_utterance_captured=MagicMock())

        assert source.open_count == 1

    @pytest.mark.unit
    def test_cleans_up_source_on_keyboard_interrupt(self) -> None:
        """capture_utterance() closes the audio source on KeyboardInterrupt."""
        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())
        vad = VoiceActivityDetector(audio_source=source)

        with pytest.raises(KeyboardInterrupt):
            vad.capture_utterance(on_utterance_captured=MagicMock())

        assert source.close_count >= 1

    @pytest.mark.unit
    def test_times_out_when_no_speech(self) -> None:
        """capture_utterance() exits cleanly when no speech is detected."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(max_wait_s=0, audio_source=source)
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        callback.assert_not_called()
        assert source.close_count >= 1

    @pytest.mark.unit
    def test_callback_called_on_speech_end(self) -> None:
        """capture_utterance() calls callback when speech end is detected."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        callback.assert_called_once()

    @pytest.mark.unit
    def test_callback_receives_captured_audio(self) -> None:
        """capture_utterance() passes a CapturedAudio to the callback."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        (audio,), _ = callback.call_args
        assert isinstance(audio, CapturedAudio)
        assert audio.sample_rate == 16000
        assert audio.channels == 1
        assert audio.samples.dtype == np.int16

    @pytest.mark.unit
    def test_buffers_audio_when_vad_returns_none_mid_speech(self) -> None:
        """capture_utterance() buffers chunks when VAD returns None mid-speech."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(
            side_effect=[{"start": 0}, None, {"end": 512}]
        )
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        callback.assert_called_once()

    @pytest.mark.unit
    def test_does_not_buffer_before_speech_starts(self) -> None:
        """capture_utterance() ignores an end event before speech starts."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(audio_source=source)
        vad._vad_iterator = MagicMock(
            side_effect=[{"end": 512}, {"start": 0}, {"end": 512}]
        )
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        callback.assert_called_once()

    @pytest.mark.unit
    def test_does_not_collect_metrics_by_default(self) -> None:
        """capture_utterance() does not collect metrics when disabled."""
        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())
        vad = VoiceActivityDetector(collect_metrics=False, audio_source=source)
        vad._collect_perf_metrics = MagicMock()

        with pytest.raises(KeyboardInterrupt):
            vad.capture_utterance(on_utterance_captured=MagicMock())

        vad._collect_perf_metrics.assert_not_called()

    @pytest.mark.unit
    def test_collects_metrics_when_enabled(self) -> None:
        """capture_utterance() collects and prints metrics when enabled."""
        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(collect_metrics=True, audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        vad._collect_perf_metrics = MagicMock(return_value={"samples": 512})
        vad._print_metrics = MagicMock()
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        vad._collect_perf_metrics.assert_called_once()
        vad._print_metrics.assert_called_once()
        callback.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.tracemalloc")
    def test_handles_tracemalloc_already_stopped(
        self, mock_tracemalloc: MagicMock
    ) -> None:
        """capture_utterance() handles tracemalloc not tracing at the end."""
        mock_tracemalloc.is_tracing.return_value = False
        mock_tracemalloc.get_traced_memory.return_value = (0, 0)

        source = FakeAudioSource(fill=_CHUNK)
        vad = VoiceActivityDetector(collect_metrics=True, audio_source=source)
        vad._vad_iterator = MagicMock(side_effect=[{"start": 0}, {"end": 512}])
        callback = MagicMock()

        vad.capture_utterance(on_utterance_captured=callback)

        mock_tracemalloc.stop.assert_not_called()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.voice_activity_detector.tracemalloc")
    def test_stops_tracemalloc_on_keyboard_interrupt(
        self, mock_tracemalloc: MagicMock
    ) -> None:
        """capture_utterance() stops tracemalloc in the finally block."""
        # First call (start check) reports not tracing, then reports tracing so
        # the finally block stops it.
        mock_tracemalloc.is_tracing.side_effect = [False, True]

        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())
        vad = VoiceActivityDetector(collect_metrics=True, audio_source=source)
        callback = MagicMock()

        with pytest.raises(KeyboardInterrupt):
            vad.capture_utterance(on_utterance_captured=callback)

        mock_tracemalloc.stop.assert_called_once()
