"""Context management for mode-specific assistant behavior."""

from voice_concierge.context.manager import ContextManager, detect_confirmation_intent
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
