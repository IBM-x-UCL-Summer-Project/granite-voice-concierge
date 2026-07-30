"""Routine step-source backends: chained, LLM, and memory providers."""

# Standard library
import json
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

    def find_candidates(self, request: str) -> tuple[Routine, ...]:
        """Return candidates from the first provider that yields any.

        A provider exposing find_candidates can offer several matches (for
        disambiguation); one exposing only get_routine yields at most one.
        """
        for provider in self._providers:
            candidates = self._candidates_from(provider, request)
            if candidates:
                return candidates
        return ()

    @staticmethod
    def _candidates_from(
        provider: RoutineProvider, request: str
    ) -> tuple[Routine, ...]:
        finder = getattr(provider, "find_candidates", None)
        if finder is not None:
            return tuple(finder(request))
        routine = provider.get_routine(request)
        return (routine,) if routine is not None else ()


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


#: Topic under which routines are stored/retrieved in the memory layer.
ROUTINE_TOPIC: str = "routine"

#: Default number of candidate routines to retrieve for a request.
DEFAULT_ROUTINE_TOP_K: int = 5


def serialize_routine(routine: Routine) -> str:
    """Serialize a routine to a single JSON string (one memory record)."""
    return json.dumps(
        {"name": routine.name, "steps": [step.text for step in routine.steps]}
    )


def deserialize_routine(content: str) -> Routine | None:
    """Parse a stored routine record, or None if it is malformed or empty."""
    try:
        data = json.loads(content)
        name = data["name"]
        steps = tuple(RoutineStep(text) for text in data["steps"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not steps:
        return None
    return Routine(name=name, steps=steps)


class MemoryRoutineProvider:
    """Loads saved routines from the memory layer (one record per routine)."""

    def __init__(
        self,
        memory_manager: object,
        *,
        topic: str = ROUTINE_TOPIC,
        top_k: int = DEFAULT_ROUTINE_TOP_K,
    ) -> None:
        self._memory = memory_manager
        self._topic = topic
        self._top_k = top_k

    def get_routine(self, request: str) -> Routine | None:
        candidates = self.find_candidates(request)
        return candidates[0] if candidates else None

    def find_candidates(self, request: str) -> tuple[Routine, ...]:
        try:
            rows = self._memory.retrieve_similar(
                query=request, top_k=self._top_k, topic=self._topic
            )
        except Exception as exc:  # backend failure -> typed routine error
            raise RoutineError(f"memory backend failed: {exc}") from exc
        routines = []
        for row in rows:
            content = row.get("content") if isinstance(row, dict) else None
            if not isinstance(content, str):
                continue
            routine = deserialize_routine(content)
            if routine is not None:
                routines.append(routine)
        return tuple(routines)
