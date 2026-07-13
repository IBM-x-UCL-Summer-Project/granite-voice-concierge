"""Backend-agnostic command spotter: maps recognized phrases to commands."""

# Local
from voice_concierge.command_control.interfaces import PhraseRecognizer
from voice_concierge.command_control.types import CommandEvent, PlaybackCommand

DEFAULT_PHRASE_COMMANDS: dict[str, PlaybackCommand] = {
    "stop": "stop",
    "pause": "pause",
    "wait": "pause",
    "continue": "resume",
}


class PhraseCommandSpotter:
    """A CommandSpotter that maps recognized phrases to playback commands.

    Recognition is delegated to any PhraseRecognizer, so the speech backend
    (Vosk today) can be swapped without changing this mapping logic.
    """

    def __init__(
        self,
        recognizer: PhraseRecognizer,
        *,
        phrase_commands: dict[str, PlaybackCommand] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._phrase_commands = dict(phrase_commands or DEFAULT_PHRASE_COMMANDS)

    def process(self, frame: bytes) -> CommandEvent | None:
        """Recognize a phrase from the frame and map it to a command event."""
        phrase = self._recognizer.recognize(frame)
        if phrase is None:
            return None
        command = self._phrase_commands.get(phrase)
        if command is None:
            return None
        return CommandEvent(command=command, phrase=phrase)
