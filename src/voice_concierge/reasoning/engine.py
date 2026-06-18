"""Reasoning engine protocol and a deterministic prototype."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from voice_concierge.reasoning.policy import memory_delete_target
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)


class ReasoningEngine(Protocol):
    """Callable interface that all local reasoning backends must implement."""

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        """Generate a voice-ready response from a transcript and local context."""


@runtime_checkable
class TraceableReasoningEngine(ReasoningEngine, Protocol):
    """Reasoning engine that exposes one generation before and after policy."""

    def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
        """Generate raw and guarded responses without a second inference."""


class RuleBasedReasoningPrototype:
    """No-dependency reasoning stub used to validate the integration contract."""

    _MODE_WORD_LIMITS = {
        "driving": 16,
        "cooking": 45,
        "shopping": 35,
        "home": 60,
    }

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        transcript = request.transcript.strip()
        if not transcript:
            return ReasoningResponse(
                spoken_response="I did not catch that. Please say it again.",
                confidence="high",
            )

        text = transcript.lower()
        response = self._generate_response(request, transcript, text)
        limit = self._effective_word_limit(request)
        return self._with_word_limit(response, limit)

    def _generate_response(
        self,
        request: ReasoningRequest,
        transcript: str,
        text: str,
    ) -> ReasoningResponse:
        if not request.constraints.offline:
            return ReasoningResponse(
                spoken_response=(
                    "This assistant is designed for offline use. I will only use "
                    "local information."
                ),
                confidence="high",
            )

        if self._looks_medical_or_emergency(text):
            return ReasoningResponse(
                spoken_response=(
                    "I cannot diagnose or make safety-critical decisions. If this "
                    "is urgent, contact emergency services."
                ),
                confidence="high",
            )

        if self._requests_web_access(text):
            return ReasoningResponse(
                spoken_response=(
                    "I cannot use the internet in offline mode. I can answer from "
                    "local information only."
                ),
                confidence="high",
            )

        if self._requests_step_repeat(text):
            return self._repeat_step_response(request)

        delete_target = memory_delete_target(transcript)
        if delete_target:
            if not request.constraints.allow_memory_writes:
                return self._memory_changes_disabled_response()

            action = MemoryAction(
                action="delete",
                content=delete_target,
                rationale="User appears to be asking for local memory deletion.",
            )
            return ReasoningResponse(
                spoken_response=(
                    "I can delete that memory. Please confirm before I remove it."
                ),
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="medium",
            )

        if request.mode.lower() == "shopping" and self._requests_shopping_list_add(
            text
        ):
            if not request.constraints.allow_memory_writes:
                return self._memory_changes_disabled_response()

            items = self._extract_shopping_items(transcript)
            action = MemoryAction(
                action="update",
                content=f"shopping_list:add:{items}",
                rationale="User appears to be asking to add shopping list items.",
            )
            return ReasoningResponse(
                spoken_response=(
                    f"I can add {items} to your shopping list. Please confirm "
                    "before I save it."
                ),
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="medium",
            )

        accessibility_preference = self._accessibility_preference(text)
        if accessibility_preference:
            if not request.constraints.allow_memory_writes:
                return self._memory_changes_disabled_response()

            content, spoken_preference = accessibility_preference
            action = MemoryAction(
                action="update",
                content=content,
                rationale="User appears to be changing an accessibility preference.",
            )
            return ReasoningResponse(
                spoken_response=(
                    f"I can {spoken_preference}. Please confirm before I save "
                    "that preference."
                ),
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="medium",
            )

        if self._requests_memory_write(text):
            if not request.constraints.allow_memory_writes:
                return self._memory_changes_disabled_response()

            content = self._extract_memory_candidate(transcript)
            action = MemoryAction(
                action="store",
                content=content,
                rationale="User appears to be asking the assistant to remember this.",
            )
            return ReasoningResponse(
                spoken_response=(
                    "I can remember that. Please confirm before I save it."
                ),
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="medium",
            )

        if self._asks_about_memory(text):
            return self._memory_response(request)

        mode = request.mode.lower()
        if mode == "shopping" and self._requests_shopping_list_read(text):
            return self._memory_response(request)

        if mode == "driving":
            return ReasoningResponse(
                spoken_response="I will keep this short. Focus on driving.",
                confidence="high",
            )

        if mode == "cooking":
            return ReasoningResponse(
                spoken_response=(
                    "I will guide you one step at a time. Tell me when you are "
                    "ready for the next step."
                ),
                confidence="medium",
            )

        if mode == "shopping":
            return ReasoningResponse(
                spoken_response=(
                    "I can help with your shopping list. I will confirm changes "
                    "before saving them."
                ),
                confidence="medium",
            )

        return ReasoningResponse(
            spoken_response=(
                "I can help with that using local information. Tell me the next "
                "detail."
            ),
            confidence="medium",
        )

    def _memory_response(self, request: ReasoningRequest) -> ReasoningResponse:
        if request.memories:
            memory = request.memories[0]
            return ReasoningResponse(
                spoken_response=f"I found this in local memory: {memory}",
                confidence="medium",
            )

        return ReasoningResponse(
            spoken_response="I do not have a saved local memory for that yet.",
            confidence="high",
        )

    def _repeat_step_response(self, request: ReasoningRequest) -> ReasoningResponse:
        if request.conversation_summary:
            return ReasoningResponse(
                spoken_response=(
                    f"The previous step was: {request.conversation_summary}"
                ),
                confidence="medium",
            )

        return ReasoningResponse(
            spoken_response=(
                "I do not have a previous step to repeat. Which step should I repeat?"
            ),
            confidence="medium",
        )

    def _effective_word_limit(self, request: ReasoningRequest) -> int:
        requested_limit = max(1, request.constraints.max_words)
        mode_limit = self._MODE_WORD_LIMITS.get(request.mode.lower(), requested_limit)
        return min(requested_limit, mode_limit)

    def _with_word_limit(
        self,
        response: ReasoningResponse,
        max_words: int,
    ) -> ReasoningResponse:
        limit = max(1, max_words)
        words = response.spoken_response.split()
        if len(words) <= limit:
            return response

        if response.needs_confirmation and response.proposed_memory_action:
            return ReasoningResponse(
                spoken_response=_confirmation_truncation_text(limit),
                needs_confirmation=response.needs_confirmation,
                proposed_memory_action=response.proposed_memory_action,
                mode_suggestion=response.mode_suggestion,
                confidence=response.confidence,
                metadata={**response.metadata, "truncated": "true"},
            )

        shortened = " ".join(words[:limit]).rstrip(".,;:")
        return ReasoningResponse(
            spoken_response=f"{shortened}.",
            needs_confirmation=response.needs_confirmation,
            proposed_memory_action=response.proposed_memory_action,
            mode_suggestion=response.mode_suggestion,
            confidence=response.confidence,
            metadata={**response.metadata, "truncated": "true"},
        )

    def _memory_changes_disabled_response(self) -> ReasoningResponse:
        return ReasoningResponse(
            spoken_response="Memory changes are disabled right now.",
            confidence="high",
        )

    def _extract_memory_candidate(self, transcript: str) -> str:
        cleaned = re.sub(
            r"^\s*(please\s+)?(remember|save|note)\s+(that\s+)?",
            "",
            transcript,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" .")

    def _extract_shopping_items(self, transcript: str) -> str:
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
        return cleaned.strip(" .")

    def _requests_shopping_list_add(self, text: str) -> bool:
        return "add " in text and "shopping list" in text

    def _requests_shopping_list_read(self, text: str) -> bool:
        return "what" in text and "shopping list" in text

    def _requests_step_repeat(self, text: str) -> bool:
        return "repeat" in text and "step" in text

    def _accessibility_preference(self, text: str) -> tuple[str, str] | None:
        if self._requests_memory_write(text):
            return None

        if "speak more slowly" in text or "answer more slowly" in text:
            return ("accessibility.preferred_pace=slow", "speak more slowly")

        if "keep answers short" in text or "short answers" in text:
            return ("accessibility.verbosity=short", "keep answers short")

        return None

    def _requests_memory_write(self, text: str) -> bool:
        return bool(re.search(r"\b(remember|save|note)\b", text))

    def _asks_about_memory(self, text: str) -> bool:
        phrases = (
            "what do you remember",
            "what did we decide",
            "how do i like",
            "what is my preference",
        )
        return any(phrase in text for phrase in phrases)

    def _requests_web_access(self, text: str) -> bool:
        return "internet" in text or "search online" in text or "look online" in text

    def _looks_medical_or_emergency(self, text: str) -> bool:
        risk_terms = (
            "diagnose",
            "chest pain",
            "medical emergency",
            "should i take",
            "medication dose",
        )
        return any(term in text for term in risk_terms)


def _confirmation_truncation_text(max_words: int) -> str:
    if max_words == 1:
        return "Confirm."

    words = ("Please", "confirm", "this", "change")
    return f"{' '.join(words[:max_words])}."
