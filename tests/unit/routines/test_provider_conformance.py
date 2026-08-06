"""Contract conformance for every RoutineProvider implementation.

Each provider is exercised through the same contract so the implementations
cannot drift apart: get_routine returns a Routine or None, a miss returns None
without raising, and any returned routine honours the >=1-step invariant.
"""

# Standard library
from collections.abc import Callable

# Third-party
import pytest

# Local
from voice_concierge.reasoning.engine import DeterministicReasoningFake
from voice_concierge.reasoning.types import ReasoningResponse
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.interfaces import RoutineProvider
from voice_concierge.routines.providers import (
    ChainedRoutineProvider,
    LLMRoutineProvider,
    MemoryRoutineProvider,
    serialize_routine,
)
from voice_concierge.routines.types import Routine, RoutineStep

_ROUTINE = Routine(name="make tea", steps=(RoutineStep("boil"), RoutineStep("pour")))
_HIT = "make tea"
_MISS = "something never stored"


class _FakeMemory:
    """Memory retrieval double returning a fixed row set."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def retrieve_similar(self, *, query: str, top_k: int, topic: str) -> list[dict]:
        return self._rows


def _static(*, hit: bool) -> RoutineProvider:
    return StaticRoutineProvider({_HIT: _ROUTINE} if hit else {})


def _chained(*, hit: bool) -> RoutineProvider:
    return ChainedRoutineProvider([_static(hit=hit)])


def _llm(*, hit: bool) -> RoutineProvider:
    text = "1. boil\n2. pour" if hit else "sorry, I don't know that one"
    return LLMRoutineProvider(DeterministicReasoningFake(ReasoningResponse(text)))


def _memory(*, hit: bool) -> RoutineProvider:
    rows = [{"content": serialize_routine(_ROUTINE)}] if hit else []
    return MemoryRoutineProvider(_FakeMemory(rows))


_MAKERS: list[Callable[..., RoutineProvider]] = [_static, _chained, _llm, _memory]


@pytest.mark.unit
@pytest.mark.parametrize("make_provider", _MAKERS)
class TestRoutineProviderContract:
    """Every provider must satisfy the same behavioural contract."""

    def test_satisfies_protocol(self, make_provider: Callable) -> None:
        assert isinstance(make_provider(hit=True), RoutineProvider)

    def test_hit_returns_valid_routine(self, make_provider: Callable) -> None:
        routine = make_provider(hit=True).get_routine(_HIT)
        assert isinstance(routine, Routine)
        assert len(routine.steps) >= 1  # documented invariant

    def test_miss_returns_none_without_raising(self, make_provider: Callable) -> None:
        assert make_provider(hit=False).get_routine(_MISS) is None
