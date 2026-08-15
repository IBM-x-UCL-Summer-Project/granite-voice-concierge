"""Backend-agnostic command spotter: maps recognized phrases to commands."""

# Local
from voice_concierge.command_control.interfaces import PhraseRecognizer
from voice_concierge.command_control.types import CommandEvent, VoiceCommand

# The single shared vocabulary: both the recognizer grammar and this mapping are
# built from it, so playback (stop/pause/resume), routine (next/back/repeat) and
# pacing (slower/faster) words are spotted through one table.
DEFAULT_PHRASE_COMMANDS: dict[str, VoiceCommand] = {
    "stop": "stop",
    "pause": "pause",
    "wait": "pause",
    "continue": "resume",
    "resume": "resume",
    "next": "next",
    "back": "back",
    "repeat": "repeat",
    # Single words only: the recognizer emits from partial results and reports
    # the last word it heard, so a two-word trigger such as "speed up" would
    # arrive as "up".
    "slower": "slower",
    "faster": "faster",
    "quicker": "faster",
    # Answers to a confirmation question. They mean nothing on their own, and a
    # caller that is not confirming anything ignores them.
    "yes": "yes",
    "no": "no",
}


class PhraseCommandSpotter:
    """A CommandSpotter that maps recognized phrases to voice commands.

    Recognition is delegated to any PhraseRecognizer, so the speech backend
    (Vosk today) can be swapped without changing this mapping logic. The mapped
    command may be a playback action or a routine-navigation action.
    """

    def __init__(
        self,
        recognizer: PhraseRecognizer,
        *,
        phrase_commands: dict[str, VoiceCommand] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._phrase_commands = dict(
            DEFAULT_PHRASE_COMMANDS if phrase_commands is None else phrase_commands
        )

    def process(self, frame: bytes) -> CommandEvent | None:
        """Recognize a phrase from the frame and map it to a command event."""
        phrase = self._recognizer.recognize(frame)
        if phrase is None:
            return None
        command = self._phrase_commands.get(phrase)
        if command is None:
            return None
        return CommandEvent(command=command, phrase=phrase)
