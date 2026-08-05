"""Deterministic fakes for the routines package."""

# Local
from voice_concierge.routines.types import Routine


class StaticRoutineProvider:
    """RoutineProvider backed by an in-memory dict. Tests never touch a model."""

    def __init__(self, routines: dict[str, Routine]) -> None:
        self._routines = {key.lower(): value for key, value in routines.items()}

    def get_routine(self, request: str) -> Routine | None:
        return self._routines.get(request.lower())
