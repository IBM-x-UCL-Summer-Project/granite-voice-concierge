# Standard library
from pathlib import Path
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import FakeAudioSource, PyAudioSource
from voice_concierge.voice_input import WakeWordDetector
from voice_concierge.voice_input.wake_word_detector import _resolve_model_reference

pytestmark = pytest.mark.usefixtures("mock_openwakeword_model")

_CHUNK_BYTES = np.zeros(1280, dtype=np.int16).tobytes()


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
    def test_creates_default_pyaudio_source(self) -> None:
        """A default PyAudioSource is created when none is injected."""
        detector = WakeWordDetector(download_models=False)
        assert isinstance(detector._audio_source, PyAudioSource)

    @pytest.mark.unit
    def test_uses_injected_audio_source(self) -> None:
        """An injected audio source is used as-is."""
        source = FakeAudioSource()
        detector = WakeWordDetector(download_models=False, audio_source=source)
        assert detector._audio_source is source

    @pytest.mark.unit
    def test_model_is_loaded_on_init(self) -> None:
        """WakeWordDetector loads the openWakeWord model on initialisation."""
        detector = WakeWordDetector(download_models=False)
        assert detector._model is not None

    @pytest.mark.unit
    @patch(
        "voice_concierge.voice_input.wake_word_detector."
        "openwakeword.utils.download_models"
    )
    def test_downloads_models_when_enabled(self, mock_download: MagicMock) -> None:
        """download_models=True triggers the openWakeWord model download."""
        WakeWordDetector(download_models=True)
        mock_download.assert_called_once()

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.Model")
    def test_model_construction_falls_back_on_typeerror(
        self, mock_model_cls: MagicMock
    ) -> None:
        """A wakeword_models TypeError falls back to wakeword_model_paths."""
        fallback_model = MagicMock()
        mock_model_cls.side_effect = [
            TypeError("unexpected keyword argument 'wakeword_models'"),
            fallback_model,
        ]

        detector = WakeWordDetector(download_models=False)

        assert detector._model is fallback_model

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.wake_word_detector.Model")
    def test_model_construction_reraises_unrelated_typeerror(
        self, mock_model_cls: MagicMock
    ) -> None:
        """An unrelated TypeError from Model construction is re-raised."""
        mock_model_cls.side_effect = TypeError("some other problem")

        with pytest.raises(TypeError):
            WakeWordDetector(download_models=False)


class TestResolveModelReference:
    """Unit tests for _resolve_model_reference()."""

    @pytest.mark.unit
    def test_returns_path_for_existing_file(self, tmp_path: Path) -> None:
        """An existing model file path is returned verbatim."""
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"")

        assert _resolve_model_reference(str(model_file)) == str(model_file)

    @pytest.mark.unit
    def test_returns_bundled_path_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bundled resource path is returned when it exists."""
        monkeypatch.setattr(Path, "is_file", lambda self: "resources" in str(self))

        result = _resolve_model_reference("hey_jarvis_v0.1.onnx")

        assert result.endswith("resources/models/hey_jarvis_v0.1.onnx")

    @pytest.mark.unit
    def test_returns_name_when_no_file_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The raw model name is returned when no file is found."""
        monkeypatch.setattr(Path, "is_file", lambda self: False)

        assert _resolve_model_reference("missing.onnx") == "missing.onnx"


class TestWakeWordDetectorListen:
    """Unit tests for WakeWordDetector.listen()."""

    @pytest.mark.unit
    def test_listen_opens_audio_source(self) -> None:
        """listen() opens the audio source before reading."""
        source = FakeAudioSource(raise_when_exhausted=KeyboardInterrupt())
        detector = WakeWordDetector(download_models=False, audio_source=source)

        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=MagicMock())

        assert source.open_count == 1

    @pytest.mark.unit
    def test_listen_closes_source_on_keyboard_interrupt(self) -> None:
        """listen() closes the audio source when interrupted with no detection."""
        source = FakeAudioSource(
            [_CHUNK_BYTES], raise_when_exhausted=KeyboardInterrupt()
        )
        detector = WakeWordDetector(download_models=False, audio_source=source)
        callback = MagicMock()

        with pytest.raises(KeyboardInterrupt):
            detector.listen(on_wake_word=callback)

        callback.assert_not_called()
        assert source.close_count == 1

    @pytest.mark.unit
    def test_listen_triggers_callback_above_threshold(self) -> None:
        """listen() fires the callback, resets, and closes on detection."""
        source = FakeAudioSource(
            [_CHUNK_BYTES], raise_when_exhausted=KeyboardInterrupt()
        )
        detector = WakeWordDetector(download_models=False, audio_source=source)
        detector._model.predict = MagicMock(return_value={"hey_jarvis_v0.1.onnx": 0.9})
        detector._model.reset = MagicMock()
        callback = MagicMock()

        detector.listen(on_wake_word=callback)

        callback.assert_called_once()
        detector._model.reset.assert_called_once()
        assert source.close_count == 1


class TestWakeWordDetectorStream:
    """Tests for transport-independent streamed sample detection."""

    @pytest.mark.unit
    def test_process_audio_returns_threshold_crossing_prediction(self) -> None:
        detector = WakeWordDetector(download_models=False)
        detector._model.predict = MagicMock(return_value={"hey_jarvis": 0.72})
        detector._model.reset = MagicMock()

        prediction = detector.process_audio(np.zeros(3200, dtype=np.int16))

        assert prediction is not None
        assert prediction.phrase == "hey_jarvis"
        assert prediction.confidence == 0.72
        detector._model.reset.assert_called_once()

    @pytest.mark.unit
    def test_process_audio_uses_supplied_stream_threshold(self) -> None:
        detector = WakeWordDetector(download_models=False)
        detector._model.predict = MagicMock(return_value={"hey_jarvis": 0.35})

        assert (
            detector.process_audio(
                np.zeros(3200, dtype=np.int16), confidence_threshold=0.4
            )
            is None
        )

    @pytest.mark.unit
    def test_process_audio_rejects_non_pcm_samples(self) -> None:
        detector = WakeWordDetector(download_models=False)

        with pytest.raises(ValueError, match="int16"):
            detector.process_audio(np.zeros(3200, dtype=np.float32))
