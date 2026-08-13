"""Tests for deterministic reasoning policy guards."""

from __future__ import annotations

from voice_concierge.reasoning.policy import apply_reasoning_policy_guards
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
)


def test_policy_guard_adds_accessibility_preference_action() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Keep answers short."),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "update"
    assert response.proposed_memory_action.content == "accessibility.verbosity=short"
    assert response.proposed_memory_action.target_key == (
        "preference:accessibility.verbosity"
    )
    assert response.metadata["policy_guard"] == "accessibility_preference_confirmation"


def test_policy_guard_prevents_missing_shopping_list_invention() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is on my shopping list?",
            mode="shopping",
        ),
        ReasoningResponse(
            spoken_response="Milk and bread are on your list.",
            needs_confirmation=True,
            confidence="medium",
        ),
    )

    assert response.spoken_response == "I do not have a saved shopping list yet."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "missing_shopping_list_memory"


def test_policy_guard_ignores_unrelated_memory_for_shopping_list_read() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is on my shopping list?",
            mode="shopping",
            memories=("User prefers short answers.",),
        ),
        ReasoningResponse(
            spoken_response="Milk and bread are on your list.",
            confidence="medium",
        ),
    )

    assert response.spoken_response == "I do not have a saved shopping list yet."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "missing_shopping_list_memory"


def test_policy_guard_prioritizes_shopping_list_over_today_word() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is on my shopping list today?",
            mode="shopping",
        ),
        ReasoningResponse(
            spoken_response="I cannot verify up-to-date information offline.",
            confidence="medium",
        ),
    )

    assert response.spoken_response == "I do not have a saved shopping list yet."
    assert response.metadata["policy_guard"] == "missing_shopping_list_memory"


def test_policy_guard_uses_supplied_shopping_list_memory() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is on my shopping list?",
            mode="shopping",
            memories=("Shopping list: milk, bread.",),
        ),
        ReasoningResponse(
            spoken_response="Eggs are on your list.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content="shopping_list:add:eggs",
                rationale="Model confused recall with update.",
            ),
            confidence="medium",
        ),
    )

    assert response.spoken_response == (
        "I found this in local memory: Shopping list: milk, bread."
    )
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "supplied_shopping_list_memory"


def test_policy_guard_blocks_time_sensitive_info_without_context() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="When is the next GTA game coming out?"),
        ReasoningResponse(
            spoken_response="It is coming out next month.",
            confidence="medium",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "offline_time_sensitive_info"


def test_policy_guard_blocks_time_sensitive_info_with_unrelated_memory() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="When is the next GTA game coming out?",
            memories=("User prefers short answers.",),
        ),
        ReasoningResponse(
            spoken_response="Your saved note says the release is tomorrow.",
            confidence="medium",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.metadata["policy_guard"] == "offline_time_sensitive_info"


def test_policy_guard_does_not_treat_bread_as_read_request() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
        ),
        ReasoningResponse(
            spoken_response="Added milk and bread.",
            needs_confirmation=True,
            confidence="medium",
        ),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "Shopping list: milk, bread."
    assert response.proposed_memory_action.target_key == "list:shopping"
    assert response.metadata["policy_guard"] == "shopping_list_add_confirmation"


def test_policy_guard_rewrites_action_without_confirmation_wording() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
        ),
        ReasoningResponse(
            spoken_response="Adding milk and bread to your shopping list.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content="shopping_list:add:milk and bread",
                rationale="User asked to add shopping list items.",
            ),
            confidence="medium",
        ),
    )

    assert response.spoken_response == (
        "I can add milk and bread to your shopping list. Please confirm before "
        "I save it."
    )
    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "Shopping list: milk, bread."
    assert response.metadata["policy_guard"] == "shopping_list_add_confirmation"


def test_policy_guard_rewrites_confirmed_action_with_wrong_content() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
        ),
        ReasoningResponse(
            spoken_response=(
                "I will add eggs to your shopping list. Please confirm before "
                "I save it."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content="shopping_list:add:eggs",
                rationale="Model extracted the wrong shopping item.",
            ),
            confidence="medium",
        ),
    )

    assert response.spoken_response == (
        "I can add milk and bread to your shopping list. Please confirm before "
        "I save it."
    )
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.content == "Shopping list: milk, bread."
    assert response.metadata["policy_guard"] == "shopping_list_add_confirmation"


def test_policy_guard_keeps_confirmed_action_with_confirmation_wording() -> None:
    original = ReasoningResponse(
        spoken_response=(
            "I will add milk and bread to your shopping list. Please confirm "
            "before I save it."
        ),
        needs_confirmation=True,
        proposed_memory_action=MemoryAction(
            action="update",
            content="shopping_list:add:milk and bread",
            rationale="User asked to add shopping list items.",
            target_key="list:shopping",
        ),
        confidence="medium",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
            memories=("Shopping list: eggs.",),
        ),
        original,
    )

    assert response is original


def test_policy_guard_adds_memory_store_action() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember that I prefer short answers."),
        ReasoningResponse(spoken_response="Understood.", confidence="medium"),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "I prefer short answers"


def test_policy_guard_adds_memory_delete_action() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Forget my old shopping list."),
        ReasoningResponse(spoken_response="Okay, forgotten.", confidence="medium"),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "delete"
    assert response.proposed_memory_action.content == "my old shopping list"
    assert response.proposed_memory_action.target_key == "list:shopping"
    assert response.metadata["policy_guard"] == "memory_delete_confirmation"


def test_policy_guard_prioritizes_delete_over_note_store_detection() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Delete the saved note from my local memory."),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "stable_memory_target_required"


def test_policy_guard_does_not_treat_cooking_remove_as_memory_delete() -> None:
    original = ReasoningResponse(
        spoken_response="Take the pan off the heat.",
        confidence="medium",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Remove the pan from the heat.",
            mode="cooking",
        ),
        original,
    )

    assert response is original


def test_policy_guard_does_not_treat_reminder_phrase_as_memory_delete() -> None:
    original = ReasoningResponse(
        spoken_response="I can help with that.",
        confidence="medium",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Don't forget to buy milk."),
        original,
    )

    assert response is original


def test_policy_guard_removes_memory_action_for_supplied_memory_recall() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="How do I like you to answer?",
            memories=("User prefers short answers.",),
        ),
        ReasoningResponse(
            spoken_response=(
                "I will keep my answers brief, as you prefer. Please confirm "
                "before saving this preference."
            ),
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="store",
                content="User prefers short answers.",
                rationale="Model treated recall as a preference save.",
            ),
            confidence="medium",
        ),
    )

    assert response.spoken_response == (
        "I found this in local memory: User prefers short answers."
    )
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "supplied_memory_recall"


def test_policy_guard_respects_disabled_memory_writes() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Remember that I prefer short answers.",
            constraints=ReasoningConstraints(allow_memory_writes=False),
        ),
        ReasoningResponse(spoken_response="Understood.", confidence="medium"),
    )

    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.spoken_response == "Memory changes are disabled right now."
    assert response.metadata["policy_guard"] == "memory_changes_disabled"


def test_policy_guard_blocks_disabled_shopping_list_update() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
            constraints=ReasoningConstraints(allow_memory_writes=False),
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.spoken_response == "Memory changes are disabled right now."
    assert response.metadata["policy_guard"] == "memory_changes_disabled"


def test_policy_guard_blocks_disabled_accessibility_update() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Keep answers short.",
            constraints=ReasoningConstraints(allow_memory_writes=False),
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.spoken_response == "Memory changes are disabled right now."
    assert response.metadata["policy_guard"] == "memory_changes_disabled"
