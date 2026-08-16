# Third-party
import pytest

# Local
from voice_concierge.reasoning.engine import DeterministicReasoningFake
from voice_concierge.reasoning.types import ReasoningResponse
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.providers import LLMRoutineProvider


def _fake(text: str) -> DeterministicReasoningFake:
    return DeterministicReasoningFake(ReasoningResponse(spoken_response=text))


@pytest.mark.unit
def test_parses_numbered_steps() -> None:
    engine = _fake("1. Boil water\n2. Add tea\n3) Pour")
    routine = LLMRoutineProvider(engine).get_routine("make tea")
    assert [s.text for s in routine.steps] == ["Boil water", "Add tea", "Pour"]
    assert routine.name == "make tea"


@pytest.mark.unit
def test_malformed_output_returns_none() -> None:
    engine = _fake("I'm not sure how to make that, sorry.")
    assert LLMRoutineProvider(engine).get_routine("make tea") is None


@pytest.mark.unit
def test_splits_numbered_steps_flattened_onto_one_line() -> None:
    engine = _fake("1. Crack the eggs. 2. Whisk them together. 3. Cook them gently.")

    routine = LLMRoutineProvider(engine).get_routine("make scrambled eggs")

    assert routine is not None
    assert [step.text for step in routine.steps] == [
        "Crack the eggs.",
        "Whisk them together.",
        "Cook them gently.",
    ]


@pytest.mark.unit
def test_nonsequential_numbered_output_is_rejected() -> None:
    engine = _fake("1. First step. 3. A disconnected fragment.")

    assert LLMRoutineProvider(engine).get_routine("make tea") is None


@pytest.mark.unit
def test_raised_backend_error_becomes_routine_error() -> None:
    class _Boom:
        def generate(self, request):
            raise RuntimeError("model down")

    with pytest.raises(RoutineError):
        LLMRoutineProvider(_Boom()).get_routine("make tea")


@pytest.mark.unit
def test_uses_raised_word_budget() -> None:
    engine = _fake("1. Step one")
    LLMRoutineProvider(engine, max_words=400).get_routine("make tea")
    assert engine.requests[0].constraints.max_words == 400
