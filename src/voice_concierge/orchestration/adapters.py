"""Compatibility adapters for the original orchestration API."""

from __future__ import annotations

from typing import Any

from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.context import SpeechPace


class OfflineTTSSpeechGateway:
    """Adapt OfflineTTS to the compatibility facade's speech port."""

    def __init__(self, tts: Any) -> None:
        self._tts = tts

    def speak(self, text: str, pace: SpeechPace) -> bool:
        return self._tts.speak(text, length_scale=_length_scale_for_pace(pace))

    def stop(self) -> bool:
        return self._tts.stop()


def _length_scale_for_pace(pace: SpeechPace) -> float:
    if pace == "slow":
        return 1.5
    return 1.2


__all__ = ["MemoryManagerGateway", "OfflineTTSSpeechGateway"]
