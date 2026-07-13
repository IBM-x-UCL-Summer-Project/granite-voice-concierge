"""Immutable captured-audio value type shared across the voice pipeline.

Stable hand-off format between components that produce audio (the voice
activity detector) and components that consume it (speech-to-text). Carries
raw PCM samples plus the metadata to serialize them into a WAV container
entirely in memory, so no audio is written to disk.
"""

# Standard library
import io
import wave
from dataclasses import dataclass
from pathlib import Path

# Third-party
import numpy as np

# Audio format defaults — 16 kHz mono int16, matching the capture pipeline
DEFAULT_SAMPLE_RATE: int = 16000  # sample rate in Hz used across voice input
DEFAULT_CHANNELS: int = 1  # mono audio
DEFAULT_SAMPLE_WIDTH: int = 2  # bytes per sample (16-bit PCM)


@dataclass(frozen=True, eq=False)
class CapturedAudio:
    """A captured mono PCM utterance with WAV serialization helpers."""

    samples: np.ndarray
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    sample_width: int = DEFAULT_SAMPLE_WIDTH

    def __post_init__(self) -> None:
        if self.samples.dtype != np.int16:
            raise ValueError(
                f"CapturedAudio requires int16 samples, got {self.samples.dtype}."
            )

    @classmethod
    def from_pcm16(
        cls,
        raw: bytes | bytearray | memoryview | np.ndarray,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
    ) -> "CapturedAudio":
        """Build from raw 16-bit PCM bytes or an int16 array."""
        if isinstance(raw, np.ndarray):
            samples = raw.astype(np.int16, copy=False)
        else:
            samples = np.frombuffer(bytes(raw), dtype=np.int16)
        return cls(samples=samples, sample_rate=sample_rate, channels=channels)

    @property
    def duration_seconds(self) -> float:
        """Utterance duration in seconds."""
        if not self.sample_rate or not self.channels:
            return 0.0
        return (len(self.samples) / self.channels) / self.sample_rate

    def to_wav_bytes(self) -> bytes:
        """Serialize the samples to an in-memory WAV container."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.samples.tobytes())
        return buffer.getvalue()

    def to_wav_stream(self) -> io.BytesIO:
        """Return a seekable in-memory WAV stream for file-like consumers."""
        return io.BytesIO(self.to_wav_bytes())

    def to_wav_file(self, path: str | Path) -> Path:
        """Write the WAV to disk and return the path (off the privacy hot path)."""
        destination = Path(path)
        destination.write_bytes(self.to_wav_bytes())
        return destination
