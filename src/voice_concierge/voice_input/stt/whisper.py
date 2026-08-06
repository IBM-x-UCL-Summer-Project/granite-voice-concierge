"""faster-whisper speech-to-text backend."""

from __future__ import annotations

# Standard library
import logging

# Third-party
try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.stt.errors import (
    SpeechToTextBackendUnavailableError,
    SpeechToTextTranscriptionError,
)
from voice_concierge.voice_input.stt.types import Transcript

logger = logging.getLogger(__name__)

# faster-whisper defaults tuned for low-latency edge CPU inference
DEFAULT_MODEL_SIZE: str = "base.en"
DEFAULT_DEVICE: str = "cpu"
DEFAULT_COMPUTE_TYPE: str = "int8"
DEFAULT_BEAM_SIZE: int = 5
DEFAULT_VAD_FILTER: bool = True


class WhisperSpeechToText:
    """SpeechToText backed by faster-whisper, consuming in-memory WAV audio."""

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL_SIZE,
        *,
        device: str = DEFAULT_DEVICE,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        beam_size: int = DEFAULT_BEAM_SIZE,
        vad_filter: bool = DEFAULT_VAD_FILTER,
        model: WhisperModel | None = None,
    ) -> None:
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        if model is not None:
            self._model = model
            return
        if WhisperModel is None:
            raise SpeechToTextBackendUnavailableError(
                "faster-whisper is required for speech-to-text model loading."
            )
        try:
            self._model = WhisperModel(
                model_size, device=device, compute_type=compute_type
            )
        except Exception as exc:
            raise SpeechToTextBackendUnavailableError(
                f"Could not load speech-to-text model {model_size!r}: {exc}"
            ) from exc

    def transcribe(self, audio: CapturedAudio) -> Transcript:
        """Transcribe captured audio by feeding an in-memory WAV to the model."""
        try:
            segments, info = self._model.transcribe(
                audio.to_wav_stream(),
                beam_size=self._beam_size,
                vad_filter=self._vad_filter,
            )
            text = " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            raise SpeechToTextTranscriptionError(
                f"Speech-to-text transcription failed: {exc}"
            ) from exc

        return Transcript(
            text=text,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
        )
