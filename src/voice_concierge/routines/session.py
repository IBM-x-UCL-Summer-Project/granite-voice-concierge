"""RoutineSession — the pure routine state machine (no audio, threads, models)."""

# Local
from voice_concierge.routines.types import (
    Routine,
    RoutineResponse,
    RoutineStatus,
    StepView,
)


class RoutineSession:
    """Tracks position in a routine and responds to navigation commands.

    Every method returns a RoutineResponse. The session never raises for a
    normal edge case; it reports one through the response outcome. Requires a
    Routine with at least one step (providers guarantee this).
    """

    def __init__(self, routine: Routine) -> None:
        self._routine = routine
        self._index = 0
        self._status: RoutineStatus = "idle"

    @property
    def status(self) -> RoutineStatus:
        return self._status

    @property
    def current_step(self) -> StepView | None:
        return self._view() if self._is_active() else None

    def start(self) -> RoutineResponse:
        self._index = 0
        self._status = "running"
        return RoutineResponse("started", self._view())

    def next(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        if self._index + 1 >= len(self._routine.steps):
            self._status = "finished"
            return RoutineResponse("finished")
        self._index += 1
        self._status = "running"
        return RoutineResponse("advanced", self._view())

    def back(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        if self._index == 0:
            self._status = "running"
            return RoutineResponse("at_start", self._view())
        self._index -= 1
        self._status = "running"
        return RoutineResponse("moved_back", self._view())

    def repeat(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        return RoutineResponse("repeated", self._view())

    def pause(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        self._status = "paused"
        return RoutineResponse("paused", self._view())

    def resume(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        self._status = "running"
        return RoutineResponse("resumed", self._view())

    def stop(self) -> RoutineResponse:
        if not self._is_active():
            return RoutineResponse("not_active")
        self._status = "stopped"
        return RoutineResponse("stopped")

    def _is_active(self) -> bool:
        return self._status in ("running", "paused")

    def _view(self) -> StepView:
        return StepView(
            number=self._index + 1,
            total=len(self._routine.steps),
            text=self._routine.steps[self._index].text,
        )
