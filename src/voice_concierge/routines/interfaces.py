"""Protocols for routine step sources."""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.routines.types import Routine


@runtime_checkable
class RoutineProvider(Protocol):
    """Supplies a routine for a spoken request, or None if it has none."""

    def get_routine(self, request: str) -> Routine | None:
        """Return a routine matching the request, or None."""
