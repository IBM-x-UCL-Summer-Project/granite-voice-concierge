# Third-party
import pytest

# Local
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.providers import ChainedRoutineProvider
from voice_concierge.routines.types import Routine, RoutineStep


def _routine(name: str) -> Routine:
    return Routine(name=name, steps=(RoutineStep("x"),))


@pytest.mark.unit
def test_chain_returns_first_non_none() -> None:
    first = StaticRoutineProvider({})  # miss
    second = StaticRoutineProvider({"tea": _routine("tea")})  # hit
    chain = ChainedRoutineProvider([first, second])
    assert chain.get_routine("tea").name == "tea"


@pytest.mark.unit
def test_chain_returns_none_when_all_miss() -> None:
    chain = ChainedRoutineProvider(
        [StaticRoutineProvider({}), StaticRoutineProvider({})]
    )
    assert chain.get_routine("tea") is None


@pytest.mark.unit
def test_chain_short_circuits_on_first_hit() -> None:
    hit = StaticRoutineProvider({"tea": _routine("early")})
    later = StaticRoutineProvider({"tea": _routine("late")})
    chain = ChainedRoutineProvider([hit, later])
    assert chain.get_routine("tea").name == "early"
