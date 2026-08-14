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

#: Commands too costly to act on when misheard, so they are confirmed first.
#: "back" undoes progress the user has already made, and a recognizer working
#: from a small grammar does occasionally hear it when nobody spoke.
DEFAULT_CONFIRM_COMMANDS: frozenset[str] = frozenset({"back"})

#: Answers that mean nothing outside a confirmation and are ignored elsewhere.
CONFIRMATION_WORDS: frozenset[str] = frozenset({"yes", "no"})

#: What is asked before acting on a command that needs confirming.
CONFIRM_PROMPTS: dict[str, str] = {
    "back": "Go back a step? Say yes to confirm.",
}

DEFAULT_CONFIRM_TIMEOUT: float = 6.0  # seconds to wait for a yes
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
        confirm_commands: frozenset[str] = DEFAULT_CONFIRM_COMMANDS,
        confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
    ) -> None:
        self._adapter = adapter
        self._speaker = speaker
        self._waiter = waiter
        self._auto_advance_delay = auto_advance_delay
        self._idle_timeout = idle_timeout
        self._confirm_commands = confirm_commands
        self._confirm_timeout = confirm_timeout

    def run(self, response: str) -> str:
        """Speak the opening response, then run the routine to completion.

        Returns the last thing said, so a caller can display or log it. Returns
        as soon as there is no active routine left to steer, which covers three
        cases: the routine finished or was stopped, it never started at all (an
        unknown request or a backend failure, where the opening line is an
        apology), and a paused routine left idle long enough that the user has
        plainly walked away.
        """
        while True:
            event = self._speaker.speak(response)
            if self._adapter.status not in _ACTIVE:
                # Nothing to steer, so do not hold the microphone open waiting
                # for a command that could not act on anything.
                return response
            event = self._next_command(event)
            if event is None:
                return response  # idle: hand control back to the caller
            response = self._adapter.handle_command(event)

    def _next_command(self, event: CommandEvent | None) -> CommandEvent | None:
        """Return the command to act on, or None to hand control back.

        Listens again rather than acting whenever a command needing
        confirmation is not confirmed, so a misheard word costs a question and
        nothing else. A stray yes or no outside a confirmation is dropped the
        same way: on its own it means nothing, and passing it on would make the
        assistant apologise for a word the user never said.
        """
        while True:
            if event is None:
                event = self._await_next()
                if event is None:
                    return None
            if event.command in CONFIRMATION_WORDS:
                event = None  # nothing is being confirmed; ignore it
                continue
            if event.command not in self._confirm_commands or self._confirmed(event):
                return event
            event = None  # not confirmed, so listen again from where we are

    def _confirmed(self, event: CommandEvent) -> bool:
        """Ask before acting, and treat anything but a yes as no.

        Silence has to mean no. The command being guarded is one the recognizer
        produces without anybody speaking, so a confirmation that could be
        satisfied by more silence would guard nothing.
        """
        prompt = CONFIRM_PROMPTS.get(event.command, f"{event.command}? Say yes.")
        answered = self._speaker.speak(prompt)  # they may answer over the question
        if answered is None:
            answered = self._waiter.wait(self._confirm_timeout)
        return answered is not None and answered.command == "yes"

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
