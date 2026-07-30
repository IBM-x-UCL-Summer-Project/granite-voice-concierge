"""Routine step-source backends: chained, LLM, and memory providers."""

# Standard library
import re
from collections.abc import Iterable

# Local
from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.reasoning.types import ReasoningConstraints, ReasoningRequest
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.interfaces import RoutineProvider
from voice_concierge.routines.types import Routine, RoutineStep


class ChainedRoutineProvider:
    """Tries each provider in order; the first non-None routine wins."""

    def __init__(self, providers: Iterable[RoutineProvider]) -> None:
        self._providers = tuple(providers)

    def get_routine(self, request: str) -> Routine | None:
        for provider in self._providers:
            routine = provider.get_routine(request)
            if routine is not None:
                return routine
        return None


#: A numbered step line: "1. text", "2) text", tolerant of leading space.
_STEP_LINE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")

#: Default word budget for a recipe (the reasoning default of 60 is too short).
DEFAULT_ROUTINE_MAX_WORDS: int = 400


def parse_numbered_steps(name: str, text: str) -> Routine | None:
    """Parse a numbered list into a Routine, or None if no steps are found."""
    steps = [
        RoutineStep(match.group(1))
        for line in text.splitlines()
        if (match := _STEP_LINE.match(line))
    ]
    if not steps:
        return None
    return Routine(name=name, steps=tuple(steps))


class LLMRoutineProvider:
    """Builds a routine by asking the reasoning engine for numbered steps."""

    def __init__(
        self,
        engine: ReasoningEngine,
        *,
        max_words: int = DEFAULT_ROUTINE_MAX_WORDS,
    ) -> None:
        self._engine = engine
        self._max_words = max_words

    def get_routine(self, request: str) -> Routine | None:
        prompt = (
            f"List the steps to: {request}. "
            "Reply as a numbered list, one step per line, nothing else."
        )
        reasoning_request = ReasoningRequest(
            transcript=prompt,
            constraints=ReasoningConstraints(max_words=self._max_words),
        )
        try:
            response = self._engine.generate(reasoning_request)
        except Exception as exc:  # backend failure -> typed routine error
            raise RoutineError(f"reasoning backend failed: {exc}") from exc
        return parse_numbered_steps(request, response.spoken_response)
