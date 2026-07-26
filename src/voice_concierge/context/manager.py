"""Rule-based context manager for the MVP assistant."""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from dataclasses import replace



from dataclasses import replace

from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import (
    AccessibilityProfile,
    CommandAction,
    ContextDecision,
    ContextMode,
    ContextState,
)

_CONFIRM_WORDS = ("yes", "confirm", "okay", "ok", "go ahead")
_CANCEL_WORDS = ("cancel", "stop", "never mind", "nevermind")


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
        if _contains_any(normalized, _CANCEL_WORDS):
            cleared_state = replace(state, pending_mode=None)
            return ContextDecision(
                state=cleared_state,
                policy=policy_for_mode(cleared_state.mode, cleared_state.accessibility),
                command_action=command_action or "cancel",
            )

        if _contains_any(normalized, _CONFIRM_WORDS):
            target_mode = state.pending_mode
            switched_state = replace(state, mode=target_mode, pending_mode=None)
            return ContextDecision(
                state=switched_state,
                policy=policy_for_mode(target_mode, switched_state.accessibility),
                mode_changed=True,
                command_action=command_action,
            )

        return None


def _normalize(transcript: str) -> str:
    return " ".join(transcript.lower().strip().split())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _detect_requested_mode(transcript: str) -> ContextMode | None:
    mode_phrases: tuple[tuple[ContextMode, tuple[str, ...]], ...] = (
        ("cooking", ("cooking mode", "kitchen mode", "switch to cooking")),
        ("shopping", ("shopping mode", "shop mode", "switch to shopping")),
        ("driving", ("driving mode", "drive mode", "switch to driving")),
        ("home", ("home mode", "living mode", "switch to home")),
    )

    for mode, phrases in mode_phrases:
        if _contains_any(transcript, phrases):
            return mode

    return None


def _detect_command_action(transcript: str) -> CommandAction | None:
    if "repeat" in transcript or "say that again" in transcript:
        return "repeat"
    if "next step" in transcript:
        return "next_step"
    if "stop" in transcript:
        return "stop"
    if (
        "cancel" in transcript
        or "never mind" in transcript
        or "nevermind" in transcript
    ):
        return "cancel"
    return None


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
            speech_pace=acc_data.get("speech_pace", "normal")
        )


        return ContextState(
            mode=data.get("mode", "home"),
            pending_mode=data.get("pending_mode"),
            last_topic=data.get("last_topic"),
            accessibility=accessibility
        )
    except (json.JSONDecodeError, KeyError, TypeError):

        return ContextState()


def get_length_scale_from_pace(pace: str) -> float:
    """
    """
    mapping = {
        "normal": 1.2,
        "slow": 1.6,
    }
    return mapping.get(pace, 1.2)