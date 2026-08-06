"""Backend-agnostic command spotter: maps recognized phrases to commands."""

# Local
from voice_concierge.command_control.interfaces import PhraseRecognizer
from voice_concierge.command_control.types import CommandEvent, VoiceCommand

# The single shared vocabulary: both the recognizer grammar and this mapping are
# built from it, so playback (stop/pause/resume) and routine (next/back/repeat)
# words are spotted through one table.
DEFAULT_PHRASE_COMMANDS: dict[str, VoiceCommand] = {
    "stop": "stop",
    "pause": "pause",
    "wait": "pause",
    "continue": "resume",
    "resume": "resume",
    "next": "next",
    "back": "back",
    "repeat": "repeat",
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
