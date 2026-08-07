"""Shared audio primitives for the voice pipeline."""

from voice_concierge.audio.duplex_player import DuplexAudioPlayer
from voice_concierge.audio.errors import AudioDeviceError, AudioError
from voice_concierge.audio.player import (
    AudioPlayer,
    FakeAudioPlayer,
    SoundDevicePlayer,
)
from voice_concierge.audio.source import (
    AudioSource,
    FakeAudioSource,
    PyAudioSource,
)
from voice_concierge.audio.streaming_player import StreamingAudioPlayer
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.audio.voice_processing_player import VoiceProcessingAudioPlayer

__all__ = [
    "AudioDeviceError",
    "AudioError",
    "AudioPlayer",
    "AudioSource",
    "CapturedAudio",
    "DuplexAudioPlayer",
    "FakeAudioPlayer",
    "FakeAudioSource",
    "PyAudioSource",
    "SoundDevicePlayer",
    "StreamingAudioPlayer",
    "VoiceProcessingAudioPlayer",
]
