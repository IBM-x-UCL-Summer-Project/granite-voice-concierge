"""Project-owned errors for the text-to-speech boundary."""


class TextToSpeechError(RuntimeError):
    """Base error for text-to-speech failures."""


class TextToSpeechBackendUnavailableError(TextToSpeechError):
    """Raised when the text-to-speech backend is unavailable."""


class TextToSpeechSynthesisError(TextToSpeechError):
    """Raised when speech synthesis fails at runtime."""
