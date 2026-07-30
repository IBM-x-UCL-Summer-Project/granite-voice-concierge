"""Tests for the routines fakes module."""

# Third-party
import pytest

# Local
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.interfaces import RoutineProvider
from voice_concierge.routines.types import Routine, RoutineStep


@pytest.mark.unit
def test_static_provider_returns_configured_routine() -> None:
    routine = Routine(name="tea", steps=(RoutineStep("boil"),))
    provider = StaticRoutineProvider({"make tea": routine})
    assert provider.get_routine("make tea") is routine


@pytest.mark.unit
def test_static_provider_returns_none_for_unknown() -> None:
    provider = StaticRoutineProvider({})
    assert provider.get_routine("nope") is None


@pytest.mark.unit
def test_static_provider_matches_case_insensitively() -> None:
    routine = Routine(name="tea", steps=(RoutineStep("boil"),))
    provider = StaticRoutineProvider({"make tea": routine})
    assert provider.get_routine("MAKE TEA") is routine


@pytest.mark.unit
def test_static_provider_satisfies_protocol() -> None:
    assert isinstance(StaticRoutineProvider({}), RoutineProvider)
