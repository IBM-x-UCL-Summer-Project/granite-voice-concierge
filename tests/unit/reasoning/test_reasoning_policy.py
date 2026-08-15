"""Tests for deterministic reasoning policy guards."""

from __future__ import annotations

import pytest

from tests.support import memory_reference, runtime_reference, user_input_evidence
from voice_concierge.reasoning.policy import apply_reasoning_policy_guards
from voice_concierge.reasoning.types import (
    InformationEvidence,
    MemoryAction,
    MemoryTarget,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
    StructuredListOperation,
)


def _add_items(
    list_name: str,
    *items: str,
) -> StructuredListOperation:
    return StructuredListOperation(
        list_name=list_name,
        operation="add_items",
        items=items,
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
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="preference:accessibility.verbosity"
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
            memories=(memory_reference("User prefers short answers."),),
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
            memories=(
                memory_reference(
                    "Shopping list: milk, bread.",
                    memory_id=10,
                    layer="feedback",
                    revision=3,
                    memory_key="list:shopping",
                    topic="shopping",
                ),
            ),
        ),
        ReasoningResponse(
            spoken_response="Eggs are on your list.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="update",
                content=None,
                rationale="Model confused recall with update.",
                target=MemoryTarget(memory_key="list:shopping"),
                list_operation=_add_items("shopping", "eggs"),
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
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == ("external_source_unavailable_offline")


def test_policy_guard_blocks_time_sensitive_info_with_unrelated_memory() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="When is the next GTA game coming out?",
            memories=(memory_reference("User prefers short answers."),),
        ),
        ReasoningResponse(
            spoken_response="Your saved note says the release is tomorrow.",
            confidence="medium",
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.metadata["policy_guard"] == ("external_source_unavailable_offline")


def test_policy_guard_uses_relevant_local_time_sensitive_context() -> None:
    saved_date = memory_reference("Saved GTA date: 26 May.")
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="When is the next GTA game coming out?",
            memories=(saved_date,),
        ),
        ReasoningResponse(
            spoken_response="It is coming out on 26 May.",
            confidence="medium",
            required_information_source="local_context",
            information_evidence=(saved_date.information_evidence(),),
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == (
        "According to your local information: It is coming out on 26 May. "
        "I cannot verify whether it is current."
    )
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == (
        "unverified_current_supplied_information"
    )


def test_policy_guard_uses_relevant_conversation_summary() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is the latest delivery status?",
            conversation_summary="The local delivery note says parcel delayed.",
        ),
        ReasoningResponse(
            spoken_response="The parcel is delayed.",
            confidence="medium",
            required_information_source="local_context",
            information_evidence=(
                InformationEvidence(
                    source="conversation_summary",
                    quote="parcel delayed",
                ),
            ),
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == (
        "According to your local information: The parcel is delayed. "
        "I cannot verify whether it is current."
    )
    assert response.metadata["policy_guard"] == (
        "unverified_current_supplied_information"
    )


def test_policy_guard_rejects_local_answer_when_model_omits_evidence() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="When is my appointment?",
            memories=(memory_reference("Appointment is at noon."),),
        ),
        ReasoningResponse(
            spoken_response="Your appointment is at noon.",
            required_information_source="local_context",
        ),
    )

    assert response.spoken_response == (
        "I could not verify which local information supports that answer."
    )
    assert response.information_evidence == ()
    assert response.metadata["policy_guard"] == "missing_local_context_evidence"


def test_policy_guard_does_not_substitute_unrelated_memory_for_missing_evidence() -> (
    None
):
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="When is my appointment?",
            memories=(memory_reference("User prefers tea."),),
        ),
        ReasoningResponse(
            spoken_response="Your appointment is at noon.",
            required_information_source="local_context",
        ),
    )

    assert response.spoken_response == (
        "I could not verify which local information supports that answer."
    )
    assert response.information_evidence == ()
    assert response.metadata["policy_guard"] == "missing_local_context_evidence"


def test_policy_guard_attributes_current_information_supplied_by_user() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="The road is closed; is that still our plan?"),
        ReasoningResponse(
            spoken_response="The road is closed.",
            required_information_source="user_input",
            information_evidence=(user_input_evidence("The road is closed"),),
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == (
        "Based on what you told me: The road is closed. "
        "I cannot verify whether it is current."
    )
    assert response.metadata["policy_guard"] == (
        "unverified_current_supplied_information"
    )


def test_policy_guard_allows_user_supplied_appointment_today() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember my appointment today."),
        ReasoningResponse(
            spoken_response="I cannot verify up-to-date information offline.",
            confidence="medium",
            required_information_source="user_input",
            information_evidence=(
                user_input_evidence("Remember my appointment today."),
            ),
        ),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "my appointment today"
    assert response.metadata["policy_guard"] == "memory_store_confirmation"


def test_policy_guard_allows_cooking_now_from_local_ingredients() -> None:
    ingredients = memory_reference(
        "Available ingredients: eggs, tomato, cheese.",
        topic="ingredients",
    )
    original = ReasoningResponse(
        spoken_response="You can make a tomato and cheese omelette.",
        confidence="medium",
        required_information_source="local_context",
        information_evidence=(ingredients.information_evidence(),),
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What can I cook now?",
            mode="cooking",
            memories=(ingredients,),
        ),
        original,
    )

    assert response is original


def test_policy_guard_still_blocks_current_weather() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="What is the weather today?"),
        ReasoningResponse(
            spoken_response="It is sunny.",
            confidence="medium",
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.metadata["policy_guard"] == ("external_source_unavailable_offline")


def test_policy_guard_still_blocks_current_clock_time() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="What time is it now?"),
        ReasoningResponse(
            spoken_response="It is three o'clock.",
            confidence="medium",
            required_information_source="runtime_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == (
        "I do not have live device information for that request."
    )
    assert response.metadata["policy_guard"] == "runtime_source_unavailable"


def test_policy_guard_uses_identified_current_runtime_fact() -> None:
    clock = runtime_reference("Local device time: 15:05.")
    original = ReasoningResponse(
        spoken_response="It is 15:05.",
        confidence="high",
        required_information_source="runtime_live",
        information_evidence=(clock.information_evidence(),),
        freshness_requirement="current",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What time is it now?",
            runtime_context=(clock,),
        ),
        original,
    )

    assert response is original


def test_policy_guard_applies_offline_guard_only_when_required() -> None:
    original = ReasoningResponse(
        spoken_response="The caller supplied the current answer.",
        confidence="medium",
        required_information_source="external_live",
        freshness_requirement="current",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="What is the weather today?",
            constraints=ReasoningConstraints(offline=False),
        ),
        original,
    )

    assert response is original


@pytest.mark.parametrize(
    "transcript",
    (
        "Remember what the weather is today.",
        "Save whether the pharmacy is open at the moment.",
        "Note when the next bus will arrive.",
    ),
)
def test_policy_guard_never_stores_a_live_information_lookup(transcript) -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript=transcript),
        ReasoningResponse(
            spoken_response="I can save that.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="store",
                content="Unverified current information.",
                rationale="Model attempted to store a lookup result.",
            ),
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None


def test_policy_guard_rejects_lookup_complement_without_source_classification() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember what the weather is today."),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.spoken_response == (
        "I need the information itself before I can remember it."
    )
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == (
        "memory_store_requires_supplied_content"
    )


@pytest.mark.parametrize(
    "transcript",
    (
        "Is the pharmacy open at the moment?",
        "How are the roads as things stand?",
        "Has the parcel arrived yet?",
        "Give me the newest score.",
    ),
)
def test_policy_guard_blocks_live_source_independent_of_temporal_wording(
    transcript,
) -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript=transcript),
        ReasoningResponse(
            spoken_response="Unverified live answer.",
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.metadata["policy_guard"] == ("external_source_unavailable_offline")


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
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "shopping", "milk", "bread"
    )
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:shopping"
    )
    assert response.metadata["policy_guard"] == "shopping_list_add_confirmation"


def test_policy_guard_handles_explicit_shopping_list_outside_shopping_mode() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk to my shopping list.",
            mode="home",
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "shopping", "milk"
    )
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:shopping"
    )
    assert response.metadata["policy_guard"] == "shopping_list_add_confirmation"


def test_policy_guard_accepts_the_list_shorthand_in_shopping_mode() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add mouth to the list",
            mode="shopping",
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "shopping", "mouth"
    )
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:shopping"
    )
    assert response.spoken_response == (
        "I can add mouth to your shopping list. Please confirm before I save it."
    )
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
                content=None,
                rationale="User asked to add shopping list items.",
                target=MemoryTarget(memory_key="list:shopping"),
                list_operation=_add_items("shopping", "milk", "bread"),
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
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "shopping", "milk", "bread"
    )
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
                content=None,
                rationale="Model extracted the wrong shopping item.",
                target=MemoryTarget(memory_key="list:shopping"),
                list_operation=_add_items("shopping", "eggs"),
            ),
            confidence="medium",
        ),
    )

    assert response.spoken_response == (
        "I can add milk and bread to your shopping list. Please confirm before "
        "I save it."
    )
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "shopping", "milk", "bread"
    )
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
            content=None,
            rationale="User asked to add shopping list items.",
            target=MemoryTarget(
                memory_id=7,
                memory_key="list:shopping",
                expected_revision=2,
            ),
            list_operation=_add_items("shopping", "milk", "bread"),
        ),
        confidence="medium",
    )

    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
            memories=(
                memory_reference(
                    "Shopping list: eggs.",
                    memory_id=7,
                    layer="feedback",
                    revision=2,
                    memory_key="list:shopping",
                    topic="shopping",
                ),
            ),
        ),
        original,
    )

    assert response is original


def test_policy_guard_stores_first_task_list_item() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Add call the dentist to my task list."),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "task", "call the dentist"
    )
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:tasks"
    )
    assert response.metadata["policy_guard"] == "task_list_add_confirmation"


def test_policy_guard_updates_existing_task_list() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Add call the dentist to my to-do list.",
            memories=(
                memory_reference(
                    "Task list: buy stamps.",
                    memory_id=9,
                    layer="feedback",
                    revision=4,
                    memory_key="list:tasks",
                    topic="task",
                ),
            ),
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "update"
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == _add_items(
        "task", "call the dentist"
    )
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_id=9,
        memory_key="list:tasks",
        expected_revision=4,
    )


def test_policy_guard_targets_task_list_delete_by_stable_key() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Delete my task list."),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "delete"
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:tasks"
    )


def test_policy_guard_adds_memory_store_action() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember that I prefer short answers."),
        ReasoningResponse(
            spoken_response="Understood.",
            confidence="medium",
            required_information_source="user_input",
            information_evidence=(
                user_input_evidence("Remember that I prefer short answers."),
            ),
        ),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "I prefer short answers"


def test_policy_guard_replaces_list_operation_for_non_list_memory_request() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember that I prefer short answers."),
        ReasoningResponse(
            spoken_response="Please confirm before I save it.",
            needs_confirmation=True,
            proposed_memory_action=MemoryAction(
                action="store",
                content=None,
                rationale="Model returned the wrong mutation type.",
                target=MemoryTarget(memory_key="list:shopping"),
                list_operation=_add_items("shopping", "short answers"),
            ),
            required_information_source="user_input",
            information_evidence=(
                user_input_evidence("Remember that I prefer short answers."),
            ),
        ),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.content == "I prefer short answers"
    assert response.proposed_memory_action.list_operation is None


def test_policy_guard_requires_user_input_source_for_memory_fact() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Remember that I prefer short answers."),
        ReasoningResponse(spoken_response="Understood.", confidence="medium"),
    )

    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == (
        "memory_store_requires_user_input_source"
    )


def test_policy_guard_adds_memory_delete_action() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(transcript="Forget my old shopping list."),
        ReasoningResponse(spoken_response="Okay, forgotten.", confidence="medium"),
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "delete"
    assert response.proposed_memory_action.content == "my old shopping list"
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="list:shopping"
    )
    assert response.metadata["policy_guard"] == "memory_delete_confirmation"


def test_policy_guard_targets_exact_supplied_memory_for_generic_delete() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Forget I prefer tea from my memory.",
            memories=(
                memory_reference(
                    "I prefer tea",
                    memory_id=37,
                    revision=4,
                ),
                memory_reference(
                    "Shopping list: milk.",
                    memory_id=38,
                    layer="feedback",
                    memory_key="list:shopping",
                ),
            ),
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_id=37,
        expected_revision=4,
    )


def test_policy_guard_rejects_ambiguous_generic_delete_target() -> None:
    response = apply_reasoning_policy_guards(
        ReasoningRequest(
            transcript="Forget I prefer tea from my memory.",
            memories=(
                memory_reference("I prefer tea", memory_id=37),
                memory_reference("I prefer tea", memory_id=38),
            ),
        ),
        ReasoningResponse(spoken_response="Okay.", confidence="medium"),
    )

    assert response.proposed_memory_action is None
    assert response.metadata["policy_guard"] == "stable_memory_target_required"


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
            memories=(memory_reference("User prefers short answers."),),
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
