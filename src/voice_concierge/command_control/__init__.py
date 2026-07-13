"""Event-driven barge-in command control for playback interruption."""

from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.errors import (
    CommandControlError,
    CommandSpotterUnavailableError,
    PlaybackControlError,
)
from voice_concierge.command_control.factory import (
    build_command_listener,
    build_vosk_command_spotter,
)
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
from voice_concierge.command_control.sounddevice_controller import (
    SoundDevicePlaybackController,
)
from voice_concierge.command_control.spotter import (
    DEFAULT_PHRASE_COMMANDS,
    PhraseCommandSpotter,
)
from voice_concierge.command_control.types import CommandEvent, PlaybackCommand
from voice_concierge.command_control.vosk_recognizer import VoskPhraseRecognizer

__all__ = [
    "DEFAULT_PHRASE_COMMANDS",
    "CommandControlError",
    "CommandDispatcher",
    "CommandEvent",
    "CommandListener",
    "CommandSpotter",
    "CommandSpotterUnavailableError",
    "FakeCommandSpotter",
    "FakePhraseRecognizer",
    "FakePlaybackController",
    "PhraseCommandSpotter",
    "PhraseRecognizer",
    "PlaybackCommand",
    "PlaybackControlError",
    "PlaybackController",
    "SoundDevicePlaybackController",
    "VoskPhraseRecognizer",
    "build_command_listener",
    "build_vosk_command_spotter",
]
