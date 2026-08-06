"""Deterministic policy guards for reasoning responses."""

from __future__ import annotations

import re

from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
)


def apply_reasoning_policy_guards(
    request: ReasoningRequest,
    response: ReasoningResponse,
) -> ReasoningResponse:
    """Apply local policy guards that should not depend on model compliance."""

    transcript = request.transcript.strip()
    text = transcript.lower()

    if _shopping_list_read_requested(text):
        shopping_list_memory = _shopping_list_memory(request.memories)
        if shopping_list_memory is None:
            return _replace_response(
                response,
                spoken_response="I do not have a saved shopping list yet.",
                needs_confirmation=False,
                proposed_memory_action=None,
                confidence="high",
                guard="missing_shopping_list_memory",
            )

        return _replace_response(
            response,
            spoken_response=f"I found this in local memory: {shopping_list_memory}",
            needs_confirmation=False,
            proposed_memory_action=None,
            confidence="high",
            guard="supplied_shopping_list_memory",
        )

    if _time_sensitive_info_requested(text):
        return _replace_response(
            response,
            spoken_response="I cannot verify up-to-date information offline.",
            needs_confirmation=False,
            proposed_memory_action=None,
            confidence="high",
            guard="offline_time_sensitive_info",
        )

    if _memory_recall_requested(text) and request.memories:
        if response.proposed_memory_action is None and not response.needs_confirmation:
            return response

        return _replace_response(
            response,
            spoken_response=f"I found this in local memory: {request.memories[0]}",
            needs_confirmation=False,
            proposed_memory_action=None,
            confidence="high",
            guard="supplied_memory_recall",
        )

    shopping_items = _shopping_items_to_add(transcript, text)
    accessibility_preference = _accessibility_preference(text)
    memory_write_requested = _memory_write_requested(text)
    delete_target = memory_delete_target(transcript)

    if not request.constraints.allow_memory_writes and _memory_change_requested(
        response=response,
        shopping_items=shopping_items,
        accessibility_preference=accessibility_preference,
        memory_write_requested=memory_write_requested,
        delete_target=delete_target,
    ):
        return _memory_changes_disabled_response(response)

    if request.mode.lower() == "shopping" and shopping_items:
        expected_content = f"shopping_list:add:{shopping_items}"
        if _has_confirmed_action_response(
            response,
            "update",
            expected_content=expected_content,
        ):
            return response

        return _replace_response(
            response,
            spoken_response=(
                f"I can add {shopping_items} to your shopping list. Please "
                "confirm before I save it."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content=expected_content,
                rationale="User asked to add shopping list items.",
            ),
            confidence="high",
            guard="shopping_list_add_confirmation",
        )

    if accessibility_preference and not memory_write_requested:
        content, spoken_preference = accessibility_preference
        if _has_confirmed_action_response(
            response,
            "update",
            expected_content=content,
        ):
            return response

        return _replace_response(
            response,
            spoken_response=(
                f"I can {spoken_preference}. Please confirm before I save "
                "that preference."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content=content,
                rationale="User asked to change an accessibility preference.",
            ),
            confidence="high",
            guard="accessibility_preference_confirmation",
        )

    if delete_target:
        if _has_confirmed_action_response(
            response,
            "delete",
            expected_content=delete_target,
        ):
            return response

        return _replace_response(
            response,
            spoken_response=(
                "I can delete that memory. Please confirm before I remove it."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="delete",
                content=delete_target,
                rationale="User asked the assistant to delete a local memory.",
            ),
            confidence="high",
            guard="memory_delete_confirmation",
        )

    if memory_write_requested:
        content = _memory_candidate(transcript)
        if _has_confirmed_action_response(
            response,
            "store",
            expected_content=content,
        ):
            return response

        return _replace_response(
            response,
            spoken_response="I can remember that. Please confirm before I save it.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="store",
                content=content,
                rationale="User asked the assistant to remember this.",
            ),
            confidence="high",
            guard="memory_store_confirmation",
        )

    return response


def _has_confirmed_action_response(
    response: ReasoningResponse,
    action: str,
    *,
    expected_content: str | None = None,
) -> bool:
    memory_action = response.proposed_memory_action
    return (
        response.needs_confirmation
        and memory_action is not None
        and memory_action.action == action
        and _has_confirmation_wording(response.spoken_response)
        and (
            expected_content is None
            or _normalized_content(memory_action.content)
            == _normalized_content(expected_content)
        )
    )


def _memory_change_requested(
    *,
    response: ReasoningResponse,
    shopping_items: str | None,
    accessibility_preference: tuple[str, str] | None,
    memory_write_requested: bool,
    delete_target: str | None,
) -> bool:
    return (
        response.proposed_memory_action is not None
        or shopping_items is not None
        or accessibility_preference is not None
        or memory_write_requested
        or delete_target is not None
    )


def _memory_changes_disabled_response(
    response: ReasoningResponse,
) -> ReasoningResponse:
    return _replace_response(
        response,
        spoken_response="Memory changes are disabled right now.",
        needs_confirmation=False,
        proposed_memory_action=None,
        confidence="high",
        guard="memory_changes_disabled",
    )


def _replace_response(
    response: ReasoningResponse,
    *,
    spoken_response: str,
    needs_confirmation: bool,
    proposed_memory_action: MemoryAction | None,
    confidence: str,
    guard: str,
) -> ReasoningResponse:
    return ReasoningResponse(
        spoken_response=spoken_response,
        needs_confirmation=needs_confirmation,
        proposed_memory_action=proposed_memory_action,
        mode_suggestion=response.mode_suggestion,
        confidence=confidence,
        metadata={**response.metadata, "policy_guard": guard},
    )


def _shopping_list_read_requested(text: str) -> bool:
    return "shopping list" in text and bool(
        re.search(
            r"\b(what|read)\b|\btell me\b|\bwhat's\b|\bwhat is\b",
            text,
        )
    )


def _time_sensitive_info_requested(text: str) -> bool:
    if re.search(
        r"\b(today|current|currently|latest|newest|recent|now|live|weather|news)\b",
        text,
    ):
        return True

    if re.search(r"\b(upcoming|next)\b", text) and re.search(
        r"\b(release|released|coming out|launch|available|date|game|movie|show)\b",
        text,
    ):
        return True

    return bool(
        re.search(r"\b(when|what date)\b", text)
        and re.search(r"\b(release|released|coming out|launch)\b", text)
    )


def _shopping_list_memory(memories: tuple[str, ...]) -> str | None:
    for memory in memories:
        if "shopping list" in memory.lower():
            return memory
    return None


def _memory_recall_requested(text: str) -> bool:
    phrases = (
        "what do you remember",
        "what did we decide",
        "how do i like",
        "what is my preference",
        "what's my preference",
    )
    return any(phrase in text for phrase in phrases)


def _shopping_items_to_add(transcript: str, text: str) -> str | None:
    if "shopping list" not in text or not re.search(r"\badd\b", text):
        return None

    cleaned = re.sub(
        r"^\s*(please\s+)?add\s+",
        "",
        transcript,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+to\s+my\s+shopping\s+list\.?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .") or None


def _accessibility_preference(text: str) -> tuple[str, str] | None:
    if "speak more slowly" in text or "answer more slowly" in text:
        return ("accessibility.preferred_pace=slow", "speak more slowly")

    if "keep answers short" in text or "short answers" in text:
        return ("accessibility.verbosity=short", "keep answers short")

    return None


def _memory_write_requested(text: str) -> bool:
    return bool(re.search(r"\b(remember|save|note)\b", text))


def memory_delete_target(transcript: str) -> str | None:
    """Return the requested local-memory delete target, if one is explicit."""

    text = transcript.strip()
    normalized = text.lower()
    if not re.search(r"\b(forget|delete|remove)\b", normalized):
        return None

    if re.search(r"\b(do not|don't)\s+forget\b|\bforget\s+to\b", normalized):
        return None

    storage_context = (
        r"\b(memory|memories|remembered|saved|profile|preference|shopping list)\b"
        r"|\bfrom\s+(my\s+)?(local\s+)?memory\b"
    )
    forget_context = r"\bforget\s+(that|what|everything|all|my)\b"
    if re.search(forget_context, normalized) or re.search(
        storage_context,
        normalized,
    ):
        return _delete_target_from_transcript(text)

    return None


def _has_confirmation_wording(text: str) -> bool:
    normalized = text.lower()
    return bool(
        re.search(
            r"\bconfirm\b"
            r"|\bbefore\s+(i\s+)?save\b"
            r"|\bbefore\s+saving\b"
            r"|\bshould i save\b"
            r"|\bwould you like me to save\b"
            r"|\bif you want me to save\b",
            normalized,
        )
    )


def _memory_candidate(transcript: str) -> str:
    cleaned = re.sub(
        r"^\s*(please\s+)?(remember|save|note)\s+(that\s+)?",
        "",
        transcript,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .")


def _delete_target_from_transcript(transcript: str) -> str:
    cleaned = re.sub(
        r"^\s*(please\s+)?(forget|delete|remove)\s+(that\s+)?",
        "",
        transcript,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+from\s+(my\s+)?(local\s+)?memor(y|ies)\.?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .") or transcript.strip(" .")


def _normalized_content(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(" .").lower())
