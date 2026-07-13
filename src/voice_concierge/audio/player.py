"""Audio playback abstraction for the voice pipeline.

Wraps speaker output behind a small AudioPlayer protocol so components that
emit audio (text-to-speech) depend on a stable interface rather than a
concrete playback backend, and tests can capture playback without a device.
"""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.types import CapturedAudio


@runtime_checkable
class AudioPlayer(Protocol):
    """Speaker playback interface consumed by audio-producing components."""

    def play(self, audio: CapturedAudio) -> None:
        """Play the given captured audio to completion."""


class SoundDevicePlayer:
    """AudioPlayer backed by the sounddevice library.

    sounddevice is imported lazily inside play() so importing the audio
    package never requires the output-only playback dependency.
    """

    def play(self, audio: CapturedAudio) -> None:
        """Play the captured audio and block until playback finishes."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioDeviceError(
                "sounddevice is required for audio playback."
            ) from exc

        try:
            sd.play(audio.samples, audio.sample_rate)
            sd.wait()
        except Exception as exc:
            raise AudioDeviceError(f"Audio playback failed: {exc}") from exc


class FakeAudioPlayer:
    """In-memory AudioPlayer for tests that records played audio."""

    def __init__(self) -> None:
        self.played: list[CapturedAudio] = []

    def play(self, audio: CapturedAudio) -> None:
        self.played.append(audio)
