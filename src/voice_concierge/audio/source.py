"""Microphone capture abstraction for the voice pipeline.

Wraps live audio input behind a small AudioSource protocol so capture
components (wake word detection, VAD) depend on a stable interface rather
than PyAudio directly, and tests can inject a fake source.
"""

# Standard library
from collections import deque
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

# Third-party
import pyaudio

# Local
from voice_concierge.audio.errors import AudioDeviceError

# Capture defaults — 16 kHz mono int16, matching the voice pipeline
DEFAULT_RATE: int = 16000  # sample rate in Hz
DEFAULT_CHANNELS: int = 1  # mono audio
DEFAULT_FORMAT: int = pyaudio.paInt16  # 16-bit PCM
DEFAULT_FRAMES_PER_BUFFER: int = 1024  # PyAudio internal buffer size


@runtime_checkable
class AudioSource(Protocol):
    """Streaming microphone interface consumed by capture components."""

    def open(self) -> None:
        """Open the underlying audio stream."""

    def read(self, num_samples: int) -> bytes:
        """Read num_samples frames and return raw 16-bit PCM bytes."""

    def close(self) -> None:
        """Close the stream and release the device."""


class PyAudioSource:
    """AudioSource backed by PyAudio live microphone input."""

    def __init__(
        self,
        rate: int = DEFAULT_RATE,
        channels: int = DEFAULT_CHANNELS,
        fmt: int = DEFAULT_FORMAT,
        frames_per_buffer: int = DEFAULT_FRAMES_PER_BUFFER,
    ) -> None:
        self._rate = rate
        self._channels = channels
        self._fmt = fmt
        self._frames_per_buffer = frames_per_buffer
        self._pyaudio: pyaudio.PyAudio | None = None
        self._stream: pyaudio.Stream | None = None

    def open(self) -> None:
        """Open the PyAudio input stream, releasing partial state on failure."""
        try:
            self._pyaudio = pyaudio.PyAudio()
            self._stream = self._pyaudio.open(
                format=self._fmt,
                channels=self._channels,
                rate=self._rate,
                input=True,
                frames_per_buffer=self._frames_per_buffer,
            )
        except Exception as exc:
            self.close()
            raise AudioDeviceError(
                f"Could not open audio input device: {exc}"
            ) from exc

    def read(self, num_samples: int) -> bytes:
        """Read num_samples frames of raw PCM from the open stream."""
        if self._stream is None:
            raise AudioDeviceError("Audio source read before open().")
        return self._stream.read(num_samples, exception_on_overflow=False)

    def close(self) -> None:
        """Stop and release the stream and PyAudio, tolerating partial state."""
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
            if self._pyaudio is not None:
                self._pyaudio.terminate()
        except Exception:
            pass
        finally:
            self._stream = None
            self._pyaudio = None

    def __enter__(self) -> "PyAudioSource":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class FakeAudioSource:
    """In-memory AudioSource for tests.

    Yields queued PCM chunks in order. Once exhausted it either repeats `fill`
    indefinitely or raises `raise_when_exhausted`, letting tests drive capture
    loops deterministically.
    """

    def __init__(
        self,
        chunks: Iterable[bytes] = (),
        *,
        fill: bytes | None = None,
        raise_when_exhausted: BaseException | None = None,
    ) -> None:
        self._chunks: deque[bytes] = deque(bytes(chunk) for chunk in chunks)
        self._fill = None if fill is None else bytes(fill)
        self._raise_when_exhausted = raise_when_exhausted
        self.open_count = 0
        self.close_count = 0

    def open(self) -> None:
        self.open_count += 1

    def read(self, num_samples: int) -> bytes:
        if self._chunks:
            return self._chunks.popleft()
        if self._raise_when_exhausted is not None:
            raise self._raise_when_exhausted
        if self._fill is not None:
            return self._fill
        raise AudioDeviceError("FakeAudioSource exhausted with no fill configured.")

    def close(self) -> None:
        self.close_count += 1

    def __enter__(self) -> "FakeAudioSource":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
