"""Framework-free backend adapter for one app pipeline turn."""

from __future__ import annotations

import base64
import binascii
import io
import wave
from collections.abc import Mapping
from typing import Any

from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.serialization import (
    JsonDict,
    PayloadValidationError,
    app_pipeline_state_from_dict,
    app_turn_options_from_dict,
    app_turn_request_from_dict,
    app_turn_result_to_dict,
)
from voice_concierge.audio.types import CapturedAudio


def handle_turn(
    payload: Mapping[str, Any],
    pipeline: VoiceConciergePipeline,
) -> JsonDict:
    """Process one serialized transcript turn through the app pipeline."""

    request = app_turn_request_from_dict(payload)
    result = pipeline.process_request(request)
    return app_turn_result_to_dict(result)


def handle_audio_turn(
    payload: Mapping[str, Any],
    pipeline: VoiceConciergePipeline,
) -> JsonDict:
    """Process one browser-recorded WAV turn through the same app pipeline."""

    audio = captured_audio_from_payload(payload)
    state = app_pipeline_state_from_dict(payload.get("state"))
    options = app_turn_options_from_dict(payload.get("options"))
    result = pipeline.process_audio(
        audio,
        state,
        synthesize=options.synthesize,
        play=options.play,
        response_length=options.response_length,
    )
    return app_turn_result_to_dict(result)


def captured_audio_from_payload(payload: Mapping[str, Any]) -> CapturedAudio:
    """Decode the audio portion of a serialized browser turn."""

    if not isinstance(payload, Mapping):
        raise PayloadValidationError("request must be an object.")
    wav_base64 = payload.get("wav_base64")
    if not isinstance(wav_base64, str) or not wav_base64:
        raise PayloadValidationError("wav_base64 must be a non-empty string.")

    try:
        wav_bytes = base64.b64decode(wav_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PayloadValidationError("wav_base64 must contain valid base64.") from exc

    return captured_audio_from_wav(wav_bytes)


def captured_audio_from_wav(wav_bytes: bytes) -> CapturedAudio:
    """Validate and decode one browser-recorded WAV payload."""

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise PayloadValidationError("WAV audio must use uncompressed PCM.")
            if wav_file.getnchannels() != 1:
                raise PayloadValidationError("WAV audio must be mono.")
            if wav_file.getsampwidth() != 2:
                raise PayloadValidationError("WAV audio must use 16-bit samples.")
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except (EOFError, wave.Error) as exc:
        raise PayloadValidationError(
            "wav_base64 must contain valid WAV audio."
        ) from exc

    if sample_rate <= 0 or not frames:
        raise PayloadValidationError("WAV audio must contain samples.")
    return CapturedAudio.from_pcm16(frames, sample_rate=sample_rate)
