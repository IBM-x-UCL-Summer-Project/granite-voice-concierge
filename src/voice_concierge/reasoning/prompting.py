"""Prompt construction for local Granite reasoning backends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from voice_concierge.reasoning.types import ReasoningRequest

Role = Literal["system", "user", "assistant"]


MODE_POLICIES = {
    "cooking": (
        "Cooking mode: answer one step at a time, keep instructions concrete, "
        "and make it easy for the user to ask for the next step or a repeat."
    ),
    "driving": (
        "Driving mode: keep responses extremely short, avoid detailed "
        "explanations, and prioritize safety over completeness."
    ),
    "home": ("Home mode: be calm, concise, and conversational while staying useful."),
    "shopping": (
        "Shopping mode: help with list recall and list changes. Confirm before "
        "saving additions, removals, or edits."
    ),
}


@dataclass(frozen=True)
class ChatMessage:
    """A generic chat message for local model runners."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        """Return a runner-friendly dictionary representation."""

        return {"role": self.role, "content": self.content}


def build_granite_messages(request: ReasoningRequest) -> tuple[ChatMessage, ...]:
    """Build local Granite chat messages from a reasoning request."""

    return (
        ChatMessage(role="system", content=_build_system_prompt(request)),
        ChatMessage(role="user", content=_build_user_prompt(request)),
    )


def _build_system_prompt(request: ReasoningRequest) -> str:
    mode = request.mode.lower()
    mode_policy = MODE_POLICIES.get(mode, MODE_POLICIES["home"])
    constraints = request.constraints

    return "\n".join(
        [
            "You are the local reasoning component for an offline voice-first "
            "assistant for independent living.",
            "Core rules:",
            "- Operate as if no internet or cloud service is available.",
            "- Use only the user transcript, supplied local memories, and supplied "
            "conversation summary.",
            "- Do not claim to browse, search online, sync, upload, or call remote "
            "services.",
            "- Keep the spoken response short, concrete, and easy to say aloud.",
            "- Do not invent remembered facts. If a memory was not supplied, say so.",
            "- Ask for explicit confirmation before saving, changing, or deleting "
            "personal data.",
            "- Do not provide medical diagnosis, medication dosing, or "
            "safety-critical decisions.",
            "- If a situation may be urgent, tell the user to contact emergency "
            "services.",
            f"- Maximum spoken response length: {constraints.max_words} words.",
            f"- Voice-first interaction required: {constraints.voice_first}.",
            f"- Memory writes allowed: {constraints.allow_memory_writes}.",
            mode_policy,
            "Structured output examples:",
            _structured_output_examples(),
        ]
    )


def _build_user_prompt(request: ReasoningRequest) -> str:
    sections = [
        f"Active mode: {request.mode}",
        _format_conversation_summary(request),
        _format_memories(request.memories),
        "User transcript:",
        request.transcript,
        "Return only a JSON object matching the configured schema. The "
        "spoken_response field must be concise and suitable for text-to-speech.",
    ]
    return "\n\n".join(sections)


def _format_conversation_summary(request: ReasoningRequest) -> str:
    if request.conversation_summary:
        return f"Conversation summary:\n{request.conversation_summary}"

    return "Conversation summary:\nNo summary supplied."


def _format_memories(memories: tuple[str, ...]) -> str:
    if not memories:
        return "Local memories:\nNo local memories supplied."

    lines = ["Local memories:"]
    lines.extend(f"- {memory}" for memory in memories)
    return "\n".join(lines)


def _structured_output_examples() -> str:
    return "\n".join(
        [
            "If the user says: Remember that I prefer short answers.",
            f"Return: {_example_json(_memory_store_example())}",
            "If the user says: Speak more slowly.",
            f"Return: {_example_json(_accessibility_update_example())}",
            "If the user asks what is on a shopping list and no local list "
            "memory is supplied, do not invent list items.",
            f"Return: {_example_json(_missing_shopping_list_example())}",
        ]
    )


def _example_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _memory_store_example() -> dict[str, object]:
    return {
        "spoken_response": "I can remember that. Please confirm before I save it.",
        "needs_confirmation": True,
        "proposed_memory_action": {
            "action": "store",
            "content": "User prefers short answers.",
            "rationale": "The user explicitly asked to remember this preference.",
            "requires_confirmation": True,
        },
        "mode_suggestion": None,
        "confidence": "high",
    }


def _accessibility_update_example() -> dict[str, object]:
    return {
        "spoken_response": (
            "I can speak more slowly. Please confirm before I save that preference."
        ),
        "needs_confirmation": True,
        "proposed_memory_action": {
            "action": "update",
            "content": "accessibility.preferred_pace=slow",
            "rationale": "The user asked to change speech pacing.",
            "requires_confirmation": True,
        },
        "mode_suggestion": None,
        "confidence": "high",
    }


def _missing_shopping_list_example() -> dict[str, object]:
    return {
        "spoken_response": "I do not have a saved shopping list yet.",
        "needs_confirmation": False,
        "proposed_memory_action": None,
        "mode_suggestion": None,
        "confidence": "high",
    }
