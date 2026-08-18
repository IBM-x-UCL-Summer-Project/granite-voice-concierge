"""Wires reminders into the live app: set them by voice, hear them when due.

Two halves. `ReminderTurnHandler` answers a spoken request to set or cancel
something, which happens inside a normal turn. `SpokenNotifier` announces a
reminder that has come due, which happens outside any turn, on the background
runner's thread.

That second half is why the notifier degrades to printing rather than raising:
if the assistant is mid-sentence, or has no speaker configured, the reminder
still has to reach the user somehow, and a raised exception on a background
thread would lose it silently.
"""

# Standard library
from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.scheduling.parser import is_reminder_request
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.types import Reminder

#: Spoken phrases that ask to hear what is currently set.
LIST_PHRASES: tuple[str, ...] = (
    "what reminders",
    "what timers",
    "my reminders",
    "list reminders",
    "any reminders",
    "do i have a reminder",
    "do i have any reminder",
    "do i have a timer",
    "do i have any timer",
)

#: Spoken phrases that ask for everything to be cleared.
CANCEL_ALL_PHRASES: tuple[str, ...] = (
    "cancel all reminders",
    "cancel my reminders",
    "clear all reminders",
    "cancel all timers",
)


@runtime_checkable
class Synthesizer(Protocol):
    """The slice of a text-to-speech backend needed to announce a reminder."""

    def synthesize(self, text: str) -> CapturedAudio:
        """Render the text to audio."""


@runtime_checkable
class Player(Protocol):
    """The slice of an audio player needed to announce a reminder."""

    def play(self, audio: CapturedAudio) -> None:
        """Play the audio."""


class SpokenNotifier:
    """Announces a due reminder aloud, falling back to text if it cannot."""

    def __init__(
        self,
        text_to_speech: Synthesizer | None = None,
        player: Player | None = None,
        *,
        write: Callable[[str], None] = print,
    ) -> None:
        self._text_to_speech = text_to_speech
        self._player = player
        self._write = write

    def notify(self, reminder: Reminder) -> None:
        """Say the reminder, or print it if speaking is not possible.

        Never raises: the runner treats a raised notifier as a failed delivery
        and retries, but a reminder that can only be printed has still reached
        the user, so reporting failure would repeat it forever.
        """
        announcement = reminder.announcement
        self._write(announcement)
        if self._text_to_speech is None or self._player is None:
            return
        try:
            self._player.play(self._text_to_speech.synthesize(announcement))
        except Exception:
            pass  # already printed, so the reminder was not lost


class ReminderTurnHandler:
    """Answers a spoken request to set, list or cancel reminders."""

    def __init__(self, service: ReminderService) -> None:
        self._service = service

    @property
    def service(self) -> ReminderService:
        """The shared service used by voice turns and background delivery."""

        return self._service

    def close(self) -> None:
        """Release the local reminder store owned by this handler."""

        self._service.close()

    def handles(self, transcript: str) -> bool:
        """True when the transcript is about reminders or timers."""
        lowered = transcript.casefold()
        return (
            is_reminder_request(transcript)
            or any(phrase in lowered for phrase in LIST_PHRASES)
            or any(phrase in lowered for phrase in CANCEL_ALL_PHRASES)
        )

    def run(self, transcript: str) -> str:
        """Carry out the request and return what should be said back."""
        lowered = transcript.casefold()
        if any(phrase in lowered for phrase in CANCEL_ALL_PHRASES):
            return self._cancel_all()
        if any(phrase in lowered for phrase in LIST_PHRASES):
            return self._describe_upcoming()
        return self._service.confirmation(self._service.create_from_speech(transcript))

    def _cancel_all(self) -> str:
        removed = self._service.cancel_all()
        if removed == 0:
            return "You have nothing set."
        plural = "reminder" if removed == 1 else "reminders"
        return f"Cancelled {removed} {plural}."

    def _describe_upcoming(self) -> str:
        """Read back what is set, in the order it will happen."""
        reminders = self._service.upcoming()
        if not reminders:
            return "You have nothing set."
        spoken = [
            f"{reminder.text}, {reminder.due_display()}" for reminder in reminders
        ]
        if len(spoken) == 1:
            return f"You have one: {spoken[0]}."
        return f"You have {len(spoken)}: " + "; ".join(spoken) + "."
