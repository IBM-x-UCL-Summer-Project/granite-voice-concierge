"""Default behavior policies for context modes."""

from __future__ import annotations

from dataclasses import replace

from voice_concierge.context.types import (
    AccessibilityProfile,
    ContextMode,
    ModePolicy,
)

_DEFAULT_POLICIES: dict[ContextMode, ModePolicy] = {
    "home": ModePolicy(
        mode="home",
        response_style="concise_conversational",
        memory_scope="personal_relevant",
        max_words=60,
    ),
    "cooking": ModePolicy(
        mode="cooking",
        response_style="step_by_step",
        memory_scope="task_relevant_only",
        max_words=55,
    ),
    "shopping": ModePolicy(
        mode="shopping",
        response_style="list_focused",
        memory_scope="list_relevant",
        max_words=50,
    ),
    "driving": ModePolicy(
        mode="driving",
        response_style="very_short_safety_aware",
        memory_scope="none",
        max_words=25,
        requires_confirmation=True,
    ),
}


def policy_for_mode(
    mode: ContextMode,
    accessibility: AccessibilityProfile,
) -> ModePolicy:
    """Return the active policy with user accessibility preferences applied."""

    policy = _DEFAULT_POLICIES[mode]
    if accessibility.verbosity == "short":
        max_words = min(policy.max_words, 45)
    else:
        max_words = policy.max_words

    return replace(
        policy,
        max_words=max_words,
        speech_pace=accessibility.speech_pace,
    )
