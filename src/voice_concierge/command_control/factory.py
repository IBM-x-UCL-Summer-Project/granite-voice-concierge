"""Construction helpers for barge-in command control."""

# Local
from voice_concierge.audio import AudioSource, PyAudioSource
from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PlaybackController,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK, CommandListener
from voice_concierge.command_control.spotter import (
    DEFAULT_PHRASE_COMMANDS,
    PhraseCommandSpotter,
)
from voice_concierge.command_control.types import PlaybackCommand
from voice_concierge.command_control.vosk_recognizer import (
    DEFAULT_MODEL_PATH,
    DEFAULT_SAMPLE_RATE,
    VoskPhraseRecognizer,
)


def build_command_listener(
    spotter: CommandSpotter,
    controller: PlaybackController,
    *,
    audio_source: AudioSource | None = None,
    chunk: int = DEFAULT_CHUNK,
) -> CommandListener:
    """Wire a spotter and playback controller into a windowed command listener."""
    dispatcher = CommandDispatcher(controller)
    source = audio_source or PyAudioSource(frames_per_buffer=chunk)
    return CommandListener(source, spotter, dispatcher.dispatch, chunk=chunk)


def build_vosk_command_spotter(
    *,
    model_path: str = DEFAULT_MODEL_PATH,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    phrase_commands: dict[str, PlaybackCommand] | None = None,
) -> PhraseCommandSpotter:
    """Build a PhraseCommandSpotter backed by a Vosk phrase recognizer."""
    commands = dict(phrase_commands or DEFAULT_PHRASE_COMMANDS)
    recognizer = VoskPhraseRecognizer(
        tuple(commands), model_path=model_path, sample_rate=sample_rate
    )
    return PhraseCommandSpotter(recognizer, phrase_commands=commands)
