"""Shared context state and decision types.

The context package owns lightweight behavior state for the assistant. It does
not call speech recognition, memory, reasoning, or text-to-speech directly; it
returns structured decisions that those components can consume later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ContextMode = Literal["home", "cooking", "shopping", "driving"]
CommandAction = Literal["repeat", "next_step", "stop", "cancel"]
ConfirmationIntent = Literal["confirm", "cancel"]
MemoryScope = Literal[
    "none",
    "personal_relevant",
    "task_relevant_only",
    "list_relevant",
]
ResponseStyle = Literal[
    "concise_conversational",
    "step_by_step",
    "list_focused",
    "very_short_safety_aware",
]
SpeechPace = Literal["slow", "normal"]
Verbosity = Literal["short", "normal"]


@dataclass(frozen=True)
class AccessibilityProfile:
    """User-controlled response preferences that context can apply."""

    verbosity: Verbosity = "normal"
    speech_pace: SpeechPace = "normal"


@dataclass(frozen=True)
class ContextState:
    """Persistent context state passed between assistant turns."""

    mode: ContextMode = "home"
    pending_mode: ContextMode | None = None
    last_topic: str | None = None
    accessibility: AccessibilityProfile = field(default_factory=AccessibilityProfile)


@dataclass(frozen=True)
class ModePolicy:
    """Mode-specific behavior hints for downstream components."""

    mode: ContextMode
    response_style: ResponseStyle
    memory_scope: MemoryScope
    max_words: int
    speech_pace: SpeechPace = "normal"
    requires_confirmation: bool = False


@dataclass(frozen=True)
class ContextDecision:
    """Result of applying context rules to one user transcript."""

    state: ContextState
    policy: ModePolicy
    mode_changed: bool = False
    command_action: CommandAction | None = None
    needs_confirmation: bool = False
    pending_mode: ContextMode | None = None
    confirmation_prompt: str = ""
