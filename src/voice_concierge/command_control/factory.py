"""Construction helpers for barge-in command control."""

# Local
from voice_concierge.audio import AudioSource, PyAudioSource
from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PlaybackController,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK, CommandListener
from voice_concierge.command_control.sounddevice_controller import (
    SoundDevicePlaybackController,
)
from voice_concierge.command_control.spotter import (
    DEFAULT_PHRASE_COMMANDS,
    PhraseCommandSpotter,
)
from voice_concierge.command_control.types import VoiceCommand
from voice_concierge.command_control.vosk_recognizer import (
    DEFAULT_MODEL_NAME,
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
    model_name: str = DEFAULT_MODEL_NAME,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    phrase_commands: dict[str, VoiceCommand] | None = None,
) -> PhraseCommandSpotter:
    """Build a PhraseCommandSpotter backed by a Vosk phrase recognizer."""
    commands = dict(phrase_commands or DEFAULT_PHRASE_COMMANDS)
    recognizer = VoskPhraseRecognizer(
        tuple(commands), model_name=model_name, sample_rate=sample_rate
    )
    return PhraseCommandSpotter(recognizer, phrase_commands=commands)


def build_playback_command_control(
    controller: PlaybackController,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    phrase_commands: dict[str, VoiceCommand] | None = None,
    audio_source: AudioSource | None = None,
    chunk: int = DEFAULT_CHUNK,
) -> CommandListener:
    """Assemble the full stop/pause/resume barge-in stack over a controller.

    Unlike build_stop_command_control, the caller supplies the controller, since
    pause and resume need one that can hold a playback position (for example
    StreamingAudioPlayer). The recognizer vocabulary is derived from the phrase
    map, so adding a phrase there is enough to make it spottable.
    """
    spotter = build_vosk_command_spotter(
        model_name=model_name,
        sample_rate=sample_rate,
        phrase_commands=phrase_commands,
    )
    return build_command_listener(
        spotter, controller, audio_source=audio_source, chunk=chunk
    )


def build_stop_command_control(
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    audio_source: AudioSource | None = None,
    chunk: int = DEFAULT_CHUNK,
) -> CommandListener:
    """Assemble the stop-only barge-in stack into a windowed command listener.

    Recognizes only "stop" (via Vosk) and stops active playback through a
    SoundDevicePlaybackController. Call listener.start() when the VAD utterance
    ends and listener.stop() when TTS output ends.
    """
    spotter = build_vosk_command_spotter(
        model_name=model_name,
        sample_rate=sample_rate,
        phrase_commands={"stop": "stop"},
    )
    controller = SoundDevicePlaybackController()
    return build_command_listener(
        spotter, controller, audio_source=audio_source, chunk=chunk
    )
