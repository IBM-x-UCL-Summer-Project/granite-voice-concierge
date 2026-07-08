"""Factory helpers for the app-level voice concierge pipeline."""

from __future__ import annotations

from voice_concierge.app.memory import MemoryGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import (
    AppReasoningConfig,
    ReasoningTurnService,
    build_reasoning_turn_service,
)
from voice_concierge.app.types import (
    AudioPlayerAdapter,
    SpeechToTextAdapter,
    TextToSpeechAdapter,
)


def build_voice_concierge_pipeline(
    config: AppReasoningConfig | None = None,
    *,
    reasoning_service: ReasoningTurnService | None = None,
    memory: MemoryGateway | None = None,
    speech_to_text: SpeechToTextAdapter | None = None,
    text_to_speech: TextToSpeechAdapter | None = None,
    audio_player: AudioPlayerAdapter | None = None,
    load_voice_io: bool = False,
) -> VoiceConciergePipeline:
    """Build the app pipeline with local backends loaded only when requested."""

    service = reasoning_service or build_reasoning_turn_service(config)

    if load_voice_io and speech_to_text is None:
        from voice_concierge.voice_input.stt.factory import build_speech_to_text

        speech_to_text = build_speech_to_text()

    if load_voice_io and text_to_speech is None:
        from voice_concierge.voice_output.factory import build_text_to_speech

        text_to_speech = build_text_to_speech()

    if load_voice_io and audio_player is None:
        from voice_concierge.audio.player import SoundDevicePlayer

        audio_player = SoundDevicePlayer()

    return VoiceConciergePipeline(
        service,
        memory=memory,
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
        audio_player=audio_player,
    )
