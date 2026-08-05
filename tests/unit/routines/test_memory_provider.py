# Standard library
import json

# Third-party
import pytest

# Local
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.providers import (
    MemoryRoutineProvider,
    deserialize_routine,
    serialize_routine,
)
from voice_concierge.routines.types import Routine, RoutineStep


class _FakeMemory:
    """Stands in for MemoryManager.retrieve_similar."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.calls: list[dict] = []

    def retrieve_similar(self, *, query: str, top_k: int, topic: str) -> list[dict]:
        self.calls.append({"query": query, "top_k": top_k, "topic": topic})
        return self._rows


def _record(name: str) -> dict:
    routine = Routine(name=name, steps=(RoutineStep("a"), RoutineStep("b")))
    return {"content": serialize_routine(routine)}


@pytest.mark.unit
def test_serialize_round_trips() -> None:
    routine = Routine(name="tea", steps=(RoutineStep("boil"), RoutineStep("pour")))
    assert deserialize_routine(serialize_routine(routine)) == routine


@pytest.mark.unit
def test_deserialize_rejects_malformed() -> None:
    assert deserialize_routine("not json") is None
    assert deserialize_routine(json.dumps({"name": "x"})) is None  # no steps key
    assert deserialize_routine(json.dumps({"name": "x", "steps": []})) is None  # empty


@pytest.mark.unit
def test_deserialize_rejects_wrong_types() -> None:
    """A non-string name or a non-list steps field is rejected."""
    assert deserialize_routine(json.dumps({"name": 5, "steps": ["a"]})) is None
    assert deserialize_routine(json.dumps({"name": "x", "steps": "a"})) is None


@pytest.mark.unit
def test_deserialize_drops_non_string_and_blank_steps() -> None:
    """Non-string and blank step entries are dropped, not turned into steps."""
    content = json.dumps({"name": "x", "steps": ["boil", 3, "", "  ", " pour "]})
    routine = deserialize_routine(content)

    assert routine is not None
    assert [step.text for step in routine.steps] == ["boil", "pour"]


@pytest.mark.unit
def test_deserialize_returns_none_when_no_valid_steps() -> None:
    """If every step entry is invalid, the record is treated as malformed."""
    assert deserialize_routine(json.dumps({"name": "x", "steps": [1, 2, ""]})) is None


@pytest.mark.unit
def test_get_routine_returns_first_match_under_routine_topic() -> None:
    memory = _FakeMemory([_record("pasta")])
    routine = MemoryRoutineProvider(memory).get_routine("pasta")
    assert routine.name == "pasta"
    assert memory.calls[0]["topic"] == "routine"


@pytest.mark.unit
def test_get_routine_returns_none_when_no_rows() -> None:
    assert MemoryRoutineProvider(_FakeMemory([])).get_routine("pasta") is None


@pytest.mark.unit
def test_find_candidates_parses_all_valid_rows() -> None:
    memory = _FakeMemory(
        [_record("pasta bake"), {"content": "corrupt"}, _record("pasta salad")]
    )
    names = [r.name for r in MemoryRoutineProvider(memory).find_candidates("pasta")]
    assert names == ["pasta bake", "pasta salad"]  # corrupt row skipped


@pytest.mark.unit
def test_find_candidates_skips_non_string_content() -> None:
    memory = _FakeMemory([{"content": None}, {"other": "x"}])
    assert MemoryRoutineProvider(memory).find_candidates("pasta") == ()


@pytest.mark.unit
def test_backend_failure_becomes_routine_error() -> None:
    class _Boom:
        def retrieve_similar(self, **_):
            raise RuntimeError("db locked")

    with pytest.raises(RoutineError):
        MemoryRoutineProvider(_Boom()).find_candidates("pasta")
