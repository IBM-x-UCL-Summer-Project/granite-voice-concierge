# Third-party
import pytest

# Local
from voice_concierge.routines.types import (
    Routine,
    RoutineResponse,
    RoutineStep,
    StepView,
)


@pytest.mark.unit
def test_routine_holds_ordered_steps() -> None:
    """A Routine keeps its steps in order as an immutable tuple."""
    routine = Routine(name="tea", steps=(RoutineStep("boil"), RoutineStep("pour")))
    assert routine.steps[0].text == "boil"
    assert routine.steps[1].text == "pour"


@pytest.mark.unit
def test_response_defaults_to_no_step() -> None:
    """A RoutineResponse carries an outcome and an optional step view."""
    response = RoutineResponse(outcome="not_active")
    assert response.outcome == "not_active"
    assert response.step is None


@pytest.mark.unit
def test_step_view_is_one_based() -> None:
    """StepView records a 1-based position and the total count."""
    view = StepView(number=1, total=3, text="boil")
    assert (view.number, view.total, view.text) == (1, 3, "boil")


@pytest.mark.unit
def test_routine_requires_at_least_one_step() -> None:
    """Constructing a Routine with no steps is rejected (documented invariant)."""
    with pytest.raises(ValueError, match="at least one step"):
        Routine(name="empty", steps=())
