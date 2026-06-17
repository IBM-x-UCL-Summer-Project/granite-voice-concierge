"""Reasoning engine protocol and a deterministic prototype."""

from __future__ import annotations

import re
from typing import Protocol

from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
)


class ReasoningEngine(Protocol):
    """Callable interface that all local reasoning backends must implement."""

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        """Generate a voice-ready response from a transcript and local context."""


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

        if self._requests_delete_memory(text):
            action = MemoryAction(
                action="delete",
                content=transcript,
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

        if self._requests_memory_write(text):
            if not request.constraints.allow_memory_writes:
                return ReasoningResponse(
                    spoken_response="Memory changes are disabled right now.",
                    confidence="high",
                )

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

    def _effective_word_limit(self, request: ReasoningRequest) -> int:
        requested_limit = max(1, request.constraints.max_words)
        mode_limit = self._MODE_WORD_LIMITS.get(request.mode.lower(), requested_limit)
        return min(requested_limit, mode_limit)

    def _with_word_limit(
        self,
        response: ReasoningResponse,
        max_words: int,
    ) -> ReasoningResponse:
        words = response.spoken_response.split()
        if len(words) <= max_words:
            return response

        shortened = " ".join(words[:max_words]).rstrip(".,;:")
        return ReasoningResponse(
            spoken_response=f"{shortened}.",
            needs_confirmation=response.needs_confirmation,
            proposed_memory_action=response.proposed_memory_action,
            mode_suggestion=response.mode_suggestion,
            confidence=response.confidence,
            metadata={**response.metadata, "truncated": "true"},
        )

    def _extract_memory_candidate(self, transcript: str) -> str:
        cleaned = re.sub(
            r"^\s*(please\s+)?(remember|save|note)\s+(that\s+)?",
            "",
            transcript,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" .")

    def _requests_memory_write(self, text: str) -> bool:
        return bool(re.search(r"\b(remember|save|note)\b", text))

    def _requests_delete_memory(self, text: str) -> bool:
        return bool(re.search(r"\b(forget|delete|remove)\b", text))

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
