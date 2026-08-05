"""Voice command types for barge-in playback control."""

# Standard library
from dataclasses import dataclass
from typing import Literal

# Playback actions a spotted voice command maps to.
PlaybackCommand = Literal["stop", "pause", "resume"]

# Routine navigation commands a spotted voice command may also carry.
RoutineCommand = Literal["next", "back", "repeat"]

# Any command a spotted voice event can represent.
VoiceCommand = Literal["stop", "pause", "resume", "next", "back", "repeat"]


@dataclass(frozen=True)
class CommandEvent:
    """A recognized voice command."""

    #: The canonical action this command maps to (playback or routine).
    command: VoiceCommand
    #: The spoken phrase that triggered it (e.g. "wait", "continue").
    phrase: str
    #: Spotter confidence in [0, 1].
    confidence: float = 1.0
