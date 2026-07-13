"""Project-owned errors for the speech-to-text boundary."""


class SpeechToTextError(RuntimeError):
    """Base error for speech-to-text failures."""


class SpeechToTextBackendUnavailableError(SpeechToTextError):
    """Raised when the speech-to-text backend cannot be initialised."""


class SpeechToTextTranscriptionError(SpeechToTextError):
    """Raised when transcription fails at runtime."""
