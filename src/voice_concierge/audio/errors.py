"""Project-owned errors for the shared audio boundary."""


class AudioError(RuntimeError):
    """Base error for audio capture and playback failures."""


class AudioDeviceError(AudioError):
    """Raised when an audio input or output device cannot be used."""
