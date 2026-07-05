"""Project-owned errors for the local reasoning boundary."""


class ReasoningError(RuntimeError):
    """Base error for reasoning runtime failures."""


class ReasoningRequestError(ValueError):
    """Raised when a caller passes an invalid reasoning request."""


class ReasoningConfigurationError(ReasoningError):
    """Raised when reasoning runtime configuration is invalid."""


class ReasoningBackendUnavailableError(ReasoningError):
    """Raised when the selected local reasoning backend is unavailable."""


class ReasoningModelUnavailableError(ReasoningError):
    """Raised when the selected local reasoning model is unavailable."""


class ReasoningTimeoutError(ReasoningError):
    """Raised when local reasoning generation exceeds its runtime timeout."""


class ReasoningGenerationError(ReasoningError):
    """Raised when local reasoning generation fails for another runtime reason."""
