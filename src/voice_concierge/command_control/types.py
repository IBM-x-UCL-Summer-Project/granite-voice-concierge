"""Voice command types for barge-in playback control."""

# Standard library
from dataclasses import dataclass
from typing import Literal

# Playback actions a spotted voice command maps to.
PlaybackCommand = Literal["stop", "pause", "resume"]


@dataclass(frozen=True)
class CommandEvent:
    """A recognized voice command that should act on playback immediately."""

    #: The canonical playback action to take.
    command: PlaybackCommand
    #: The spoken phrase that triggered it (e.g. "wait", "continue").
    phrase: str
    #: Spotter confidence in [0, 1].
    confidence: float = 1.0
