"""Production adapters for orchestration ports."""

from __future__ import annotations

from typing import Any

from voice_concierge.context import MemoryScope, SpeechPace
from voice_concierge.reasoning.types import MemoryAction


class MemoryManagerGateway:
    """Adapt MemoryManager to the orchestrator memory port."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        limit: int = 3,
    ) -> tuple[str, ...]:
        if scope == "none":
            return ()

        topic = _topic_for_scope(scope)
        memories = self._manager.retrieve_similar(
            query,
            top_k=limit,
            topic=topic,
        )
        return tuple(
            memory["content"]
            for memory in memories
            if isinstance(memory, dict) and isinstance(memory.get("content"), str)
        )

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        if action.action == "store" and scope == "list_relevant":
            success, reason, _ = self._manager.store_memory(
                content=action.content,
                layer="feedback",
                topic="shopping",
                validate=False,
            )
            return success, reason

        return self._manager.process_memory_action(action)


class OfflineTTSSpeechGateway:
    """Adapt OfflineTTS to the orchestrator speech port."""

    def __init__(self, tts: Any) -> None:
        self._tts = tts

    def speak(self, text: str, pace: SpeechPace) -> bool:
        return self._tts.speak(text, length_scale=_length_scale_for_pace(pace))

    def stop(self) -> bool:
        return self._tts.stop()


def _topic_for_scope(scope: MemoryScope) -> str | None:
    if scope == "task_relevant_only":
        return "procedural"
    if scope == "list_relevant":
        return "shopping"
    return None


def _length_scale_for_pace(pace: SpeechPace) -> float:
    if pace == "slow":
        return 1.5
    return 1.2
