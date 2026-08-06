"""Shared audio primitives for the voice pipeline."""

from __future__ import annotations

from typing import Any

from voice_concierge.audio.errors import AudioDeviceError, AudioError
from voice_concierge.audio.types import CapturedAudio

__all__ = [
    "AudioDeviceError",
    "AudioError",
    "AudioPlayer",
    "AudioSource",
    "CapturedAudio",
    "FakeAudioPlayer",
    "FakeAudioSource",
    "PyAudioSource",
    "SoundDevicePlayer",
    "StreamingAudioPlayer",
]


def __getattr__(name: str) -> Any:
    modules = {
        "AudioPlayer": "voice_concierge.audio.player",
        "FakeAudioPlayer": "voice_concierge.audio.player",
        "SoundDevicePlayer": "voice_concierge.audio.player",
        "AudioSource": "voice_concierge.audio.source",
        "FakeAudioSource": "voice_concierge.audio.source",
        "PyAudioSource": "voice_concierge.audio.source",
        "StreamingAudioPlayer": "voice_concierge.audio.streaming_player",
    }
    module_name = modules.get(name)
    if module_name is None:
        raise AttributeError(name)
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
