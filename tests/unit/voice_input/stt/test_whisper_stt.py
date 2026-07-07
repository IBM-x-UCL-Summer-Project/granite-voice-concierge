# Standard library
import types
from unittest.mock import MagicMock, patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.stt import (
    SpeechToText,
    SpeechToTextBackendUnavailableError,
    SpeechToTextTranscriptionError,
    WhisperSpeechToText,
)


def _audio() -> CapturedAudio:
    """Return a short silent utterance for transcription tests."""
    return CapturedAudio(samples=np.zeros(320, dtype=np.int16))


def _segment(text: str) -> types.SimpleNamespace:
    """Return a fake faster-whisper segment with the given text."""
    return types.SimpleNamespace(text=text)


class TestWhisperSpeechToTextInit:
    """Unit tests for WhisperSpeechToText construction."""

    @pytest.mark.unit
    def test_uses_injected_model(self) -> None:
        """An injected model is used directly without loading a new one."""
        model = MagicMock()

        stt = WhisperSpeechToText(model=model)

        assert stt._model is model

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.stt.whisper.WhisperModel")
    def test_constructs_default_model(self, mock_model_cls: MagicMock) -> None:
        """Without an injected model, a WhisperModel is built from the config."""
        WhisperSpeechToText(
            model_size="base.en", device="cpu", compute_type="int8"
        )

        mock_model_cls.assert_called_once_with(
            "base.en", device="cpu", compute_type="int8"
        )

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.stt.whisper.WhisperModel")
    def test_wraps_model_load_failure(self, mock_model_cls: MagicMock) -> None:
        """A model load failure is wrapped in SpeechToTextBackendUnavailableError."""
        mock_model_cls.side_effect = RuntimeError("no model")

        with pytest.raises(SpeechToTextBackendUnavailableError):
            WhisperSpeechToText()

    @pytest.mark.unit
    def test_satisfies_speech_to_text_protocol(self) -> None:
        """WhisperSpeechToText satisfies the runtime-checkable protocol."""
        assert isinstance(WhisperSpeechToText(model=MagicMock()), SpeechToText)


class TestWhisperSpeechToTextTranscribe:
    """Unit tests for WhisperSpeechToText.transcribe()."""

    @pytest.mark.unit
    def test_joins_segments_and_maps_metadata(self) -> None:
        """transcribe() joins segment text and maps language metadata."""
        info = types.SimpleNamespace(language="en", language_probability=0.9)
        model = MagicMock()
        model.transcribe.return_value = ([_segment("hello"), _segment("world")], info)
        stt = WhisperSpeechToText(model=model, beam_size=5, vad_filter=True)
        audio = _audio()

        transcript = stt.transcribe(audio)

        assert transcript.text == "hello world"
        assert transcript.language == "en"
        assert transcript.language_probability == 0.9
        # The model receives an in-memory WAV stream plus the configured args.
        _, kwargs = model.transcribe.call_args
        assert kwargs == {"beam_size": 5, "vad_filter": True}

    @pytest.mark.unit
    def test_wraps_transcription_failure(self) -> None:
        """A transcription failure is wrapped in SpeechToTextTranscriptionError."""
        model = MagicMock()
        model.transcribe.side_effect = RuntimeError("boom")
        stt = WhisperSpeechToText(model=model)

        with pytest.raises(SpeechToTextTranscriptionError):
            stt.transcribe(_audio())
