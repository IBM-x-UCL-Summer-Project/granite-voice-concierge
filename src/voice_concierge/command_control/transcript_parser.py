"""Parse voice commands from a finalized transcript (the wake-word path).

The always-on KWS spotter and this parser share one phrase->command vocabulary
(``DEFAULT_PHRASE_COMMANDS``), so navigation words are recognized whether spoken
as a bare keyword to the listener or inside a wake-word utterance transcribed by
speech-to-text. Both paths emit the same ``CommandEvent``.
"""

# Standard library
import re

# Local
from voice_concierge.command_control.spotter import DEFAULT_PHRASE_COMMANDS
from voice_concierge.command_control.types import CommandEvent, VoiceCommand

# Word tokens, lower-cased and stripped of punctuation.
_WORD = re.compile(r"[a-z]+")


class TranscriptCommandParser:
    """Extracts the first recognized command word from a transcript."""

    def __init__(
        self,
        *,
        phrase_commands: dict[str, VoiceCommand] | None = None,
    ) -> None:
        self._phrase_commands = dict(phrase_commands or DEFAULT_PHRASE_COMMANDS)

    def parse(self, transcript: str) -> CommandEvent | None:
        """Return a CommandEvent for the first command word found, or None."""
        for word in _WORD.findall(transcript.lower()):
            command = self._phrase_commands.get(word)
            if command is not None:
                return CommandEvent(command=command, phrase=word)
        return None
