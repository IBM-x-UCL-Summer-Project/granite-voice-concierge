"""A short rolling window of the most recent microphone audio.

The wake word is only recognised once it has been fully spoken, and the
recogniser works a chunk at a time, so by the time it fires the speaker is
already a few hundred milliseconds into whatever came next. Anyone saying
"Hey Jarvis, how do I make scrambled eggs" in one breath has their first words
swallowed by the detection itself.

Keeping the last second or so of audio on hand solves that: when the wake word
fires, the words already spoken are still held and can be put in front of the
utterance rather than lost. This is the same approach commercial assistants
take, and it is why they can be addressed in a single sentence.

The buffer only holds bytes and forgets old ones, which makes it exact to test
and cheap enough to feed on every chunk of a live stream.
"""

# Standard library
from typing import Final

#: Bytes per sample for the 16-bit PCM the capture stack uses throughout.
DEFAULT_SAMPLE_WIDTH: Final[int] = 2

#: Sample rate shared by the wake word recogniser and the speech gate.
DEFAULT_RATE: Final[int] = 16000

#: How much history to keep. Long enough to cover the wake word itself plus the
#: first words after it, short enough that a stray earlier noise has gone.
DEFAULT_PREROLL_SECONDS: Final[float] = 1.5


class RollingAudioBuffer:
    """Keeps the most recent audio, discarding whatever no longer fits.

    Stores raw little-endian 16-bit PCM exactly as it comes off the device, so
    the contents can be handed straight to a recogniser without conversion.
    """

    def __init__(
        self,
        *,
        max_seconds: float = DEFAULT_PREROLL_SECONDS,
        rate: int = DEFAULT_RATE,
        sample_width: int = DEFAULT_SAMPLE_WIDTH,
    ) -> None:
        if max_seconds <= 0:
            raise ValueError("max_seconds must be positive.")
        if rate <= 0:
            raise ValueError("rate must be positive.")
        if sample_width <= 0:
            raise ValueError("sample_width must be positive.")

        self._sample_width = sample_width
        # Rounded to whole samples so trimming can never split one in half and
        # turn the retained audio into noise.
        self._max_bytes = int(max_seconds * rate) * sample_width
        self._buffer = bytearray()

    @property
    def max_bytes(self) -> int:
        """The most this buffer will ever hold."""
        return self._max_bytes

    def __len__(self) -> int:
        """How many bytes are currently held."""
        return len(self._buffer)

    def extend(self, chunk: bytes) -> None:
        """Add a chunk, dropping the oldest audio to stay within the window.

        Rejects a chunk that is not whole samples: a misaligned write shifts
        every following sample by a byte, which turns speech into noise and is
        very hard to trace back from the far end of the pipeline.
        """
        if len(chunk) % self._sample_width:
            raise ValueError(
                f"chunk of {len(chunk)} bytes is not a whole number of "
                f"{self._sample_width}-byte samples."
            )

        self._buffer.extend(chunk)
        overflow = len(self._buffer) - self._max_bytes
        if overflow > 0:
            del self._buffer[:overflow]

    def snapshot(self) -> bytes:
        """Everything currently held, oldest first, as an immutable copy."""
        return bytes(self._buffer)

    def clear(self) -> None:
        """Forget everything held.

        Called once the contents have been handed to an utterance, so the next
        wake word does not inherit audio from the previous turn.
        """
        self._buffer.clear()
