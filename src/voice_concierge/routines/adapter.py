# src/voice_concierge/routines/adapter.py
"""RoutineCommandAdapter — maps voice commands onto a routine session.

The only place in the routines package that produces English. It turns a
command_control CommandEvent into a session call and formats the outcome, owns
starting a routine (with ask-then-default disambiguation), and degrades a
backend failure to a generic spoken fallback.
"""

# Local
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.providers import provider_candidates
from voice_concierge.routines.session import RoutineSession
from voice_concierge.routines.types import Routine, RoutineResponse

_NOT_RUNNING = "No routine is running."
_NOT_FOUND = "I don't have a routine for that."
_BACKEND_FALLBACK = "I couldn't load that routine right now."
_STEP_PREFIX = {
    "paused": "Paused. ",
    "resumed": "Resuming. ",
    "at_start": "You're at the start. ",
}


class RoutineCommandAdapter:
    """Drives a RoutineSession from spoken commands and speaks the outcome."""

    def __init__(self, provider: object) -> None:
        self._provider = provider
        self._session: RoutineSession | None = None
        self._pending: tuple[Routine, ...] = ()

    def start_routine(self, request: str) -> str:
        self._pending = ()  # a new start-request abandons any pending disambiguation
        try:
            candidates = provider_candidates(self._provider, request)
        except RoutineError:
            return _BACKEND_FALLBACK
        if not candidates:
            return _NOT_FOUND
        if len(candidates) == 1:
            return self._begin(candidates[0])
        self._pending = candidates
        names = " or ".join(routine.name for routine in candidates)
        return f"I found more than one. Did you mean {names}?"

    def resolve_choice(self, reply: str) -> str:
        if not self._pending:
            return "There's nothing to choose."
        chosen = self._pending[0]  # default: most recent
        for routine in self._pending:
            if routine.name.lower() in reply.lower():
                chosen = routine
                break
        self._pending = ()
        return self._begin(chosen)

    def handle_command(self, event: CommandEvent) -> str:
        if self._session is None:
            return _NOT_RUNNING
        method = {
            "next": self._session.next,
            "back": self._session.back,
            "repeat": self._session.repeat,
            "pause": self._session.pause,
            "resume": self._session.resume,
            "stop": self._session.stop,
        }[event.command]
        return self._speak(method())

    def _begin(self, routine: Routine) -> str:
        self._session = RoutineSession(routine)
        return self._speak(self._session.start())

    def _speak(self, response: RoutineResponse) -> str:
        if response.outcome == "finished":
            return "That was the last step."
        if response.outcome == "stopped":
            return "Routine stopped."
        if response.outcome == "not_active":
            return _NOT_RUNNING
        step = response.step
        prefix = _STEP_PREFIX.get(response.outcome, "")
        return f"{prefix}Step {step.number} of {step.total}. {step.text}"
