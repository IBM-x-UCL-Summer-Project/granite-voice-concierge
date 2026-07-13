"""Construction helpers for barge-in command control."""

# Local
from voice_concierge.audio import AudioSource, PyAudioSource
from voice_concierge.command_control.dispatcher import CommandDispatcher
from voice_concierge.command_control.interfaces import (
    CommandSpotter,
    PlaybackController,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK, CommandListener


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
