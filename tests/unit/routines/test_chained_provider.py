# Third-party
import pytest

# Local
from voice_concierge.routines.errors import RoutineError
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


class _MultiProvider:
    """Provider exposing find_candidates (like the memory provider)."""

    def __init__(self, routines: list, *, error: bool = False) -> None:
        self._routines = routines
        self._error = error

    def get_routine(self, request: str):
        return self._routines[0] if self._routines else None

    def find_candidates(self, request: str) -> tuple:
        if self._error:
            raise RoutineError("boom")
        return tuple(self._routines)


@pytest.mark.unit
def test_find_candidates_returns_first_providers_matches() -> None:
    multi = _MultiProvider([_routine("x"), _routine("y")])
    chain = ChainedRoutineProvider([multi, StaticRoutineProvider({})])
    assert [r.name for r in chain.find_candidates("q")] == ["x", "y"]


@pytest.mark.unit
def test_find_candidates_falls_through_to_get_routine_provider() -> None:
    empty = _MultiProvider([])  # find_candidates -> ()
    static = StaticRoutineProvider({"tea": _routine("tea")})  # get_routine hit
    chain = ChainedRoutineProvider([empty, static])
    assert [r.name for r in chain.find_candidates("tea")] == ["tea"]


@pytest.mark.unit
def test_find_candidates_returns_empty_when_all_miss() -> None:
    chain = ChainedRoutineProvider([_MultiProvider([]), StaticRoutineProvider({})])
    assert chain.find_candidates("q") == ()


@pytest.mark.unit
def test_find_candidates_propagates_backend_error() -> None:
    chain = ChainedRoutineProvider([_MultiProvider([], error=True)])
    with pytest.raises(RoutineError):
        chain.find_candidates("q")
