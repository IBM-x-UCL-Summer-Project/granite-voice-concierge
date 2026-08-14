"""Rule-based context manager for the MVP assistant."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from pathlib import Path

from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import (
    AccessibilityProfile,
    CommandAction,
    ConfirmationIntent,
    ContextDecision,
    ContextMode,
    ContextState,
)

_MODE_ALIASES: tuple[tuple[ContextMode, tuple[str, ...]], ...] = (
    ("cooking", ("cooking", "kitchen")),
    ("shopping", ("shopping", "shop")),
    ("driving", ("driving", "drive")),
    ("home", ("home", "living")),
)

_QUESTION_PREFIXES = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
)

_CONFIRM_WORDS = ("yes", "confirm", "okay", "ok", "go ahead")
_CANCEL_WORDS = ("no", "cancel", "stop", "never mind", "nevermind")


class ContextManager:
    """Apply explicit context rules to a single transcribed user turn."""

    def handle(
        self,
        transcript: str,
        state: ContextState | None = None,
    ) -> ContextDecision:
        """Return context state and behavior policy for a transcript."""

        current_state = state or ContextState()
        normalized = _normalize(transcript)
        command_action = _detect_command_action(normalized)

        if current_state.pending_mode is not None:
            pending_decision = self._handle_pending_mode(
                normalized,
                current_state,
                command_action,
            )
            if pending_decision is not None:
                return pending_decision

        accessibility = _apply_accessibility_preferences(
            normalized,
            current_state.accessibility,
        )
        updated_state = replace(current_state, accessibility=accessibility)
        requested_mode = _detect_requested_mode(normalized)

        if requested_mode == "driving" and updated_state.mode != "driving":
            pending_state = replace(updated_state, pending_mode="driving")
            return ContextDecision(
                state=pending_state,
                policy=policy_for_mode(updated_state.mode, accessibility),
                command_action=command_action,
                needs_confirmation=True,
                pending_mode="driving",
                confirmation_prompt=(
                    "Driving mode uses very short, safety-aware responses. "
                    "Please confirm before I switch."
                ),
            )

        if requested_mode is not None and requested_mode != updated_state.mode:
            switched_state = replace(
                updated_state,
                mode=requested_mode,
                pending_mode=None,
            )
            return ContextDecision(
                state=switched_state,
                policy=policy_for_mode(requested_mode, accessibility),
                mode_changed=True,
                command_action=command_action,
            )

        stable_state = replace(updated_state, pending_mode=None)
        return ContextDecision(
            state=stable_state,
            policy=policy_for_mode(stable_state.mode, stable_state.accessibility),
            command_action=command_action,
        )

    def _handle_pending_mode(
        self,
        normalized: str,
        state: ContextState,
        command_action: CommandAction | None,
    ) -> ContextDecision | None:
        confirmation_intent = detect_confirmation_intent(normalized)

        if confirmation_intent == "cancel":
            cleared_state = replace(state, pending_mode=None)
            return ContextDecision(
                state=cleared_state,
                policy=policy_for_mode(cleared_state.mode, cleared_state.accessibility),
                command_action=command_action or "cancel",
            )

        if confirmation_intent == "confirm":
            target_mode = state.pending_mode
            switched_state = replace(state, mode=target_mode, pending_mode=None)
            return ContextDecision(
                state=switched_state,
                policy=policy_for_mode(target_mode, switched_state.accessibility),
                mode_changed=True,
                command_action=command_action,
            )

        # "I mentioned that yesterday"
        return ContextDecision(
            state=state,
            policy=policy_for_mode(state.mode, state.accessibility),
            command_action=command_action,
            needs_confirmation=True,
            pending_mode=state.pending_mode,
            confirmation_prompt="Sorry, was that a yes or a no?",
        )


def _normalize(transcript: str) -> str:
    return " ".join(transcript.lower().strip().split())


def detect_confirmation_intent(transcript: str) -> ConfirmationIntent | None:
    """Return an explicit confirmation intent from a user transcript."""

    normalized = _normalize(transcript)
    if _contains_any(normalized, _CANCEL_WORDS):
        return "cancel"
    if _contains_any(normalized, _CONFIRM_WORDS):
        return "confirm"
    return None


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        pattern = rf"\b{re.escape(phrase)}\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _detect_requested_mode(transcript: str) -> ContextMode | None:
    if _is_question(transcript):
        return None

    for mode, aliases in _MODE_ALIASES:
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        target = rf"(?:{alias_pattern})(?:\s+(?:mode|mdoe))?"
        patterns = (
            rf"^(?:please\s+)?(?:switch|change)(?:\s+back)?\s+(?:me\s+)?to\s+"
            rf"(?:the\s+)?{target}(?:\s+please)?[.!]*$",
            rf"^(?:please\s+)?go\s+(?:me\s+)?to\s+"
            rf"(?:the\s+)?{target}(?:\s+please)?[.!]*$",
            rf"^(?:please\s+)?(?:enter|enable|activate|start|use)\s+"
            rf"(?:the\s+)?{target}(?:\s+please)?[.!]*$",
            rf"^(?:please\s+)?(?:{alias_pattern})\s+mode(?:\s+please)?[.!]*$",
        )
        if any(re.fullmatch(pattern, transcript) for pattern in patterns):
            return mode

    return None


def _detect_command_action(transcript: str) -> CommandAction | None:
    if _matches_command(
        transcript,
        r"(?:repeat(?:\s+(?:that|this|it))?|say\s+that\s+again)",
    ):
        return "repeat"
    if _matches_command(
        transcript,
        r"(?:next\s+step|what(?:'s|\s+is)\s+the\s+next\s+step)",
    ):
        return "next_step"
    if _matches_command(
        transcript,
        r"stop(?:\s+(?:speaking|talking|that|this|now|the\s+response|playback))?",
    ):
        return "stop"
    if _matches_command(
        transcript,
        r"(?:cancel(?:\s+(?:that|this))?|never\s+mind|nevermind)",
    ):
        return "cancel"
    return None


def _matches_command(transcript: str, command_pattern: str) -> bool:
    """Return whether the whole transcript is an explicit command."""

    pattern = rf"^(?:please\s+)?{command_pattern}(?:\s+please)?[.!]*$"
    return re.fullmatch(pattern, transcript) is not None


def _is_question(transcript: str) -> bool:
    """Return whether a transcript is phrased as a question, not a mode command."""

    if transcript.rstrip().endswith("?"):
        return True
    first_word = transcript.split(maxsplit=1)[0].rstrip(".,!?") if transcript else ""
    return first_word in _QUESTION_PREFIXES


def _apply_accessibility_preferences(
    transcript: str,
    accessibility: AccessibilityProfile,
) -> AccessibilityProfile:
    updated = accessibility

    if "keep answers short" in transcript or "short answers" in transcript:
        updated = replace(updated, verbosity="short")
    if "answer more slowly" in transcript or "speak more slowly" in transcript:
        updated = replace(updated, speech_pace="slow")

    return updated


# ==========================================
# Persistence & Restoration
# ==========================================

DEFAULT_STATE_FILE = Path(".voice_concierge_state.json")


def save_context_state(state: ContextState, path: Path = DEFAULT_STATE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)


def load_context_state(path: Path = DEFAULT_STATE_FILE) -> ContextState:
    if not path.exists():
        return ContextState()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        acc_data = data.get("accessibility", {})
        accessibility = AccessibilityProfile(
            verbosity=acc_data.get("verbosity", "normal"),
            speech_pace=acc_data.get("speech_pace", "normal"),
        )

        return ContextState(
            mode=data.get("mode", "home"),
            pending_mode=data.get("pending_mode"),
            last_topic=data.get("last_topic"),
            accessibility=accessibility,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return ContextState()


def get_length_scale_from_pace(pace: str) -> float:
    """Map a persisted speech pace to a Piper length scale."""
    mapping = {
        "normal": 1.2,
        "slow": 1.6,
    }
    return mapping.get(pace, 1.2)
