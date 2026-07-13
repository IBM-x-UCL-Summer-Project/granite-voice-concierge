"""Construction helpers for the voice input pipeline."""

# Local
from voice_concierge.audio import AudioSource
from voice_concierge.voice_input.interfaces import UtteranceCapturer, WakeWordListener
from voice_concierge.voice_input.voice_activity_detector import VoiceActivityDetector
from voice_concierge.voice_input.voice_input_pipeline import VoiceInputPipeline
from voice_concierge.voice_input.wake_word_detector import WakeWordDetector


def build_voice_input_pipeline(
    *,
    wake_word_detector: WakeWordListener | None = None,
    voice_activity_detector: UtteranceCapturer | None = None,
    audio_source: AudioSource | None = None,
) -> VoiceInputPipeline:
    """Build the default voice input pipeline for application code."""
    wake_word = wake_word_detector or WakeWordDetector(audio_source=audio_source)
    vad = voice_activity_detector or VoiceActivityDetector(audio_source=audio_source)
    return VoiceInputPipeline(
        wake_word_detector=wake_word,
        voice_activity_detector=vad,
    )
