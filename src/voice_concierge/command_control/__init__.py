"""Event-driven barge-in command control for playback interruption."""

from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.factory import build_command_listener
from voice_concierge.command_control.fakes import (
    FakeCommandSpotter,
    FakePhraseRecognizer,
    FakePlaybackController,
)
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PhraseRecognizer,
    PlaybackController,
)
from voice_concierge.command_control.listener import CommandListener
from voice_concierge.command_control.spotter import (
    DEFAULT_PHRASE_COMMANDS,
    PhraseCommandSpotter,
)
from voice_concierge.command_control.types import CommandEvent, PlaybackCommand

__all__ = [
    "DEFAULT_PHRASE_COMMANDS",
    "CommandDispatcher",
    "CommandEvent",
    "CommandListener",
    "CommandSpotter",
    "FakeCommandSpotter",
    "FakePhraseRecognizer",
    "FakePlaybackController",
    "PhraseCommandSpotter",
    "PhraseRecognizer",
    "PlaybackCommand",
    "PlaybackController",
    "build_command_listener",
]
