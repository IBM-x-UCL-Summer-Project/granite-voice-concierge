"""RoutineRunner — drives a routine hands-free from step to step.

The adapter answers "what should I say for this command"; this runner answers
"when does the next command happen". It reads a step, gives the user a short
window to steer, and moves on by itself if they stay quiet, so following a
routine needs no wake word and no hands between steps.

Commands reach it from two places, and it treats them the same: barged in over
the speech (StepSpeaker) or spoken into the quiet gap after it (CommandWaiter).
A paused routine never auto-advances; it waits quietly until told to continue,
which is what makes "pause" usable while your hands are busy.

All audio is behind the two protocols, so the whole policy is testable with
fakes and no device.
"""

# Local
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.interfaces import CommandWaiter, StepSpeaker

DEFAULT_AUTO_ADVANCE_DELAY: float = 6.0  # quiet seconds before the next step
DEFAULT_IDLE_TIMEOUT: float = 120.0  # quiet seconds a paused routine waits
AUTO_ADVANCE_PHRASE = "(auto-advance)"  # stands in for a spoken "next" in logs

_ACTIVE = ("running", "paused")


class RoutineRunner:
    """Runs a started routine to its end, auto-advancing between steps."""

    def __init__(
        self,
        adapter: RoutineCommandAdapter,
        speaker: StepSpeaker,
        waiter: CommandWaiter,
        *,
        auto_advance_delay: float = DEFAULT_AUTO_ADVANCE_DELAY,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        self._adapter = adapter
        self._speaker = speaker
        self._waiter = waiter
        self._auto_advance_delay = auto_advance_delay
        self._idle_timeout = idle_timeout

    def run(self, response: str) -> str:
        """Speak the opening response, then run the routine to completion.

        Returns the last thing said, so a caller can display or log it. Returns
        as soon as the routine ends (finished or stopped) or a paused routine is
        left idle long enough that the user has plainly walked away.
        """
        while True:
            event = self._speaker.speak(response)
            if event is None:
                event = self._await_next()
                if event is None:
                    return response  # idle: hand control back to the caller
            response = self._adapter.handle_command(event)
            if self._adapter.status not in _ACTIVE:
                self._speaker.speak(response)  # say the closing line, then stop
                return response

    def _await_next(self) -> CommandEvent | None:
        """Listen after a step; fall back to advancing when nothing is said."""
        paused = self._adapter.status == "paused"
        timeout = self._idle_timeout if paused else self._auto_advance_delay
        event = self._waiter.wait(timeout)
        if event is not None:
            return event
        if self._adapter.status == "running":
            # Silence during a running routine means "carry on".
            return CommandEvent(command="next", phrase=AUTO_ADVANCE_PHRASE)
        return None
