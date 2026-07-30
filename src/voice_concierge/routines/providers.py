"""Routine step-source backends: chained, LLM, and memory providers."""

# Standard library
from collections.abc import Iterable

# Local
from voice_concierge.routines.interfaces import RoutineProvider
from voice_concierge.routines.types import Routine


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
