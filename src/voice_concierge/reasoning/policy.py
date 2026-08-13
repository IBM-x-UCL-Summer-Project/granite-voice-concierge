"""Deterministic policy guards for reasoning responses."""

from __future__ import annotations

import re
from dataclasses import replace

from voice_concierge.reasoning.information_policy import decide_information_policy
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
)

SHOPPING_LIST_MEMORY_KEY = "list:shopping"
TASK_LIST_MEMORY_KEY = "list:tasks"


def apply_reasoning_policy_guards(
    request: ReasoningRequest,
    response: ReasoningResponse,
) -> ReasoningResponse:
    """Apply local policy guards that should not depend on model compliance."""

    transcript = request.transcript.strip()
    text = transcript.lower()
    shopping_items = _shopping_items_to_add(transcript, text)
    task_items = _task_items_to_add(transcript, text)
    accessibility_preference = _accessibility_preference(text)
    memory_write_requested = _memory_write_requested(text)
    delete_target = memory_delete_target(transcript)

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

    information_decision = decide_information_policy(request, response)
    if not information_decision.allowed:
        assert information_decision.spoken_response is not None
        return _replace_response(
            response,
            spoken_response=information_decision.spoken_response,
            needs_confirmation=False,
            proposed_memory_action=None,
            confidence="high",
            guard=information_decision.disposition,
        )

    if information_decision.attribution_prefix is not None:
        spoken_response = (
            f"{information_decision.attribution_prefix} "
            f"{response.spoken_response.rstrip()}"
        )
        if not _has_freshness_caveat(spoken_response):
            spoken_response = (
                f"{spoken_response} I cannot verify whether it is current."
            )
        response = replace(
            response,
            spoken_response=spoken_response,
            metadata={
                **response.metadata,
                "policy_guard": "unverified_current_supplied_information",
            },
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

    if not request.constraints.allow_memory_writes and _memory_change_requested(
        response=response,
        shopping_items=shopping_items,
        task_items=task_items,
        accessibility_preference=accessibility_preference,
        memory_write_requested=memory_write_requested,
        delete_target=delete_target,
    ):
        return _memory_changes_disabled_response(response)

    if request.mode.lower() == "shopping" and shopping_items:
        shopping_list_memory = _shopping_list_memory(request.memories)
        action = "update" if shopping_list_memory is not None else "store"
        expected_content = (
            f"shopping_list:add:{shopping_items}"
            if action == "update"
            else _new_shopping_list_content(shopping_items)
        )
        if _has_confirmed_action_response(
            response,
            action,
            expected_content=expected_content,
            expected_target_key=SHOPPING_LIST_MEMORY_KEY,
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
                action=action,
                content=expected_content,
                rationale="User asked to add shopping list items.",
                target_key=SHOPPING_LIST_MEMORY_KEY,
            ),
            confidence="high",
            guard="shopping_list_add_confirmation",
        )

    if task_items:
        task_list_memory = _task_list_memory(request.memories)
        action = "update" if task_list_memory is not None else "store"
        expected_content = (
            f"task_list:add:{task_items}"
            if action == "update"
            else _new_structured_list_content("Task list", task_items)
        )
        if _has_confirmed_action_response(
            response,
            action,
            expected_content=expected_content,
            expected_target_key=TASK_LIST_MEMORY_KEY,
        ):
            return response

        return _replace_response(
            response,
            spoken_response=(
                f"I can add {task_items} to your task list. Please confirm "
                "before I save it."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action=action,
                content=expected_content,
                rationale="User asked to add task list items.",
                target_key=TASK_LIST_MEMORY_KEY,
            ),
            confidence="high",
            guard="task_list_add_confirmation",
        )

    if accessibility_preference and not memory_write_requested:
        content, spoken_preference = accessibility_preference
        target_key = _accessibility_target_key(content)
        if _has_confirmed_action_response(
            response,
            "update",
            expected_content=content,
            expected_target_key=target_key,
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
                target_key=target_key,
            ),
            confidence="high",
            guard="accessibility_preference_confirmation",
        )

    if delete_target:
        target_key = _delete_target_key(delete_target)
        if target_key is None:
            return _replace_response(
                response,
                spoken_response=(
                    "I cannot safely identify that saved memory to delete."
                ),
                needs_confirmation=False,
                proposed_memory_action=None,
                confidence="high",
                guard="stable_memory_target_required",
            )
        if _has_confirmed_action_response(
            response,
            "delete",
            expected_content=delete_target,
            expected_target_key=target_key,
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
                target_key=target_key,
            ),
            confidence="high",
            guard="memory_delete_confirmation",
        )

    if memory_write_requested:
        if not _memory_request_supplies_content(transcript):
            if response.required_information_source in {
                "user_input",
                "local_context",
                "stable_knowledge",
            } and _has_confirmed_action_response(response, "store"):
                return response

            return _replace_response(
                response,
                spoken_response=(
                    "I need the information itself before I can remember it."
                ),
                needs_confirmation=False,
                proposed_memory_action=None,
                confidence="high",
                guard="memory_store_requires_supplied_content",
            )

        if response.required_information_source != "user_input":
            return _replace_response(
                response,
                spoken_response=(
                    "I could not verify that you supplied a fact to remember."
                ),
                needs_confirmation=False,
                proposed_memory_action=None,
                confidence="high",
                guard="memory_store_requires_user_input_source",
            )

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
    expected_target_key: str | None = None,
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
        and (
            expected_target_key is None
            or memory_action.target_key == expected_target_key
        )
    )


def _memory_change_requested(
    *,
    response: ReasoningResponse,
    shopping_items: str | None,
    task_items: str | None,
    accessibility_preference: tuple[str, str] | None,
    memory_write_requested: bool,
    delete_target: str | None,
) -> bool:
    return (
        response.proposed_memory_action is not None
        or shopping_items is not None
        or task_items is not None
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
        required_information_source=response.required_information_source,
        freshness_requirement=response.freshness_requirement,
        metadata={**response.metadata, "policy_guard": guard},
    )


def _shopping_list_read_requested(text: str) -> bool:
    return "shopping list" in text and bool(
        re.search(
            r"\b(what|read)\b|\btell me\b|\bwhat's\b|\bwhat is\b",
            text,
        )
    )


def _shopping_list_memory(memories: tuple[str, ...]) -> str | None:
    for memory in memories:
        if "shopping list" in memory.lower():
            return memory
    return None


def _task_list_memory(memories: tuple[str, ...]) -> str | None:
    for memory in memories:
        if "task list" in memory.lower():
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


def _task_items_to_add(transcript: str, text: str) -> str | None:
    list_name = r"(?:task|to-do|todo)\s+list"
    if not re.search(rf"\b{list_name}\b", text) or not re.search(r"\badd\b", text):
        return None

    cleaned = re.sub(
        r"^\s*(please\s+)?add\s+",
        "",
        transcript,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\s+to\s+(?:my|the)\s+{list_name}\.?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .") or None


def _new_shopping_list_content(items: str) -> str:
    return _new_structured_list_content("Shopping list", items)


def _new_structured_list_content(label: str, items: str) -> str:
    parts = re.split(r"\s*,\s*|\s+and\s+", items, flags=re.IGNORECASE)
    normalized = [part.strip(" .") for part in parts if part.strip(" .")]
    return f"{label}: {', '.join(normalized)}."


def _accessibility_preference(text: str) -> tuple[str, str] | None:
    if "speak more slowly" in text or "answer more slowly" in text:
        return ("accessibility.preferred_pace=slow", "speak more slowly")

    if "keep answers short" in text or "short answers" in text:
        return ("accessibility.verbosity=short", "keep answers short")

    return None


def _accessibility_target_key(content: str) -> str:
    setting = content.partition("=")[0]
    return f"preference:{setting}"


def _delete_target_key(target: str) -> str | None:
    normalized = target.lower()
    if "shopping list" in normalized:
        return SHOPPING_LIST_MEMORY_KEY
    if re.search(r"\b(task|to-do|todo)\s+list\b", normalized):
        return TASK_LIST_MEMORY_KEY
    if "short answer" in normalized or "verbosity" in normalized:
        return "preference:accessibility.verbosity"
    if "speak" in normalized and "slow" in normalized:
        return "preference:accessibility.preferred_pace"
    return None


def _memory_write_requested(text: str) -> bool:
    return bool(re.search(r"\b(remember|save|note)\b", text))


def _memory_request_supplies_content(transcript: str) -> bool:
    candidate = _memory_candidate(transcript).lower()
    if candidate.endswith("?"):
        return False
    return not bool(
        re.match(
            r"^(what|who|when|where|why|how|whether|if)\b"
            r"|^(find|check|look up|get|tell me)\b",
            candidate,
        )
    )


def memory_delete_target(transcript: str) -> str | None:
    """Return the requested local-memory delete target, if one is explicit."""

    text = transcript.strip()
    normalized = text.lower()
    if not re.search(r"\b(forget|delete|remove)\b", normalized):
        return None

    if re.search(r"\b(do not|don't)\s+forget\b|\bforget\s+to\b", normalized):
        return None

    storage_context = (
        r"\b(memory|memories|remembered|saved|profile|preference|"
        r"shopping list|task list|to-do list|todo list)\b"
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


def _has_freshness_caveat(text: str) -> bool:
    normalized = text.lower()
    return bool(
        re.search(
            r"\b(cannot|can't|unable to)\b.*\b(verify|confirm)\b.*\bcurrent\b"
            r"|\bmay not be current\b",
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
