"""Context management for mode-specific assistant behavior."""

from voice_concierge.context.manager import (
    CONFIRMATION_CLARIFICATION_PROMPT,
    ContextManager,
    detect_confirmation_intent,
)
from voice_concierge.context.types import (
    AccessibilityProfile,
    CommandAction,
    ConfirmationIntent,
    ContextDecision,
    ContextMode,
    ContextState,
    MemoryScope,
    ModePolicy,
    ResponseStyle,
    SpeechPace,
    Verbosity,
)

__all__ = [
    "AccessibilityProfile",
    "CommandAction",
    "CONFIRMATION_CLARIFICATION_PROMPT",
    "ConfirmationIntent",
    "ContextDecision",
    "ContextManager",
    "ContextMode",
    "ContextState",
    "MemoryScope",
    "ModePolicy",
    "ResponseStyle",
    "SpeechPace",
    "Verbosity",
    "detect_confirmation_intent",
]
