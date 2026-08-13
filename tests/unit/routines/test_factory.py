# tests/unit/routines/test_factory.py
# Third-party
import pytest

# Local
from voice_concierge.memory import MemoryRecord, MemorySearchResult
from voice_concierge.reasoning.engine import DeterministicReasoningFake
from voice_concierge.reasoning.types import ReasoningResponse
from voice_concierge.routines import RoutineCommandAdapter, build_routine_adapter
from voice_concierge.routines.providers import ChainedRoutineProvider


class _FakeMemory:
    def retrieve_similar(self, *, query, top_k, topic):
        return []


@pytest.mark.unit
def test_build_routine_adapter_wires_memory_then_llm() -> None:
    engine = DeterministicReasoningFake(
        ReasoningResponse(spoken_response="1. Boil\n2. Pour")
    )
    adapter = build_routine_adapter(
        memory_manager=_FakeMemory(), reasoning_engine=engine
    )
    assert isinstance(adapter, RoutineCommandAdapter)
    # memory misses (no rows) -> LLM fallback builds the routine
    assert "Step 1 of 2" in adapter.start_routine("make tea")


@pytest.mark.unit
def test_build_routine_adapter_uses_a_chain() -> None:
    engine = DeterministicReasoningFake(ReasoningResponse(spoken_response="1. x"))
    adapter = build_routine_adapter(
        memory_manager=_FakeMemory(), reasoning_engine=engine
    )
    assert isinstance(adapter._provider, ChainedRoutineProvider)


@pytest.mark.unit
def test_built_adapter_asks_when_memory_has_multiple_matches() -> None:
    from voice_concierge.routines.providers import serialize_routine
    from voice_concierge.routines.types import Routine, RoutineStep

    def _rec(name: str) -> MemorySearchResult:
        content = serialize_routine(Routine(name=name, steps=(RoutineStep("a"),)))
        return MemorySearchResult(
            memory=MemoryRecord(
                id=1,
                content=content,
                layer="profile",
                memory_key=None,
                revision=1,
                indexed_revision=1,
                deleted_at=None,
                created_at=1,
                event_time=None,
                last_accessed=None,
                strength=1,
                person=None,
                source_type=None,
                topic="routine",
            ),
            distance=0.1,
        )

    class _Mem:
        def retrieve_similar(self, *, query, top_k, topic):
            return [_rec("pasta bake"), _rec("pasta salad")]

    engine = DeterministicReasoningFake(ReasoningResponse(spoken_response="1. x"))
    adapter = build_routine_adapter(memory_manager=_Mem(), reasoning_engine=engine)
    said = adapter.start_routine("pasta")
    assert "pasta bake" in said and "pasta salad" in said  # it asks
