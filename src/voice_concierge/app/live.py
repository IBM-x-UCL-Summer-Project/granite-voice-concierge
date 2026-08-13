"""Live local E2E runner for the app pipeline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from voice_concierge.app.factory import build_voice_concierge_pipeline
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.types import AppPipelineState, AppTurnResult
from voice_concierge.audio import CapturedAudio, PyAudioSource
from voice_concierge.reasoning import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelUnavailableError,
)
from voice_concierge.voice_input.interfaces import UtteranceCapturer, WakeWordListener
from voice_concierge.voice_input.voice_activity_detector import (
    DEFAULT_CHUNK as DEFAULT_VAD_CHUNK,
)
from voice_concierge.voice_input.voice_activity_detector import (
    DEFAULT_MAX_WAIT_S,
    VoiceActivityDetector,
)
from voice_concierge.voice_input.wake_word_detector import (
    DEFAULT_CHUNK as DEFAULT_WAKE_WORD_CHUNK,
)
from voice_concierge.voice_input.wake_word_detector import (
    DEFAULT_CONFIDENCE_THRESHOLD as DEFAULT_WAKE_WORD_THRESHOLD,
)
from voice_concierge.voice_input.wake_word_detector import (
    DEFAULT_RATE,
    WakeWordDetector,
)

DEFAULT_WAKE_WORD_MODEL = "hey_jarvis_v0.1.onnx"


@dataclass(frozen=True)
class LiveAppConfig:
    """Runtime options for the live local E2E runner."""

    use_wake_word: bool = True
    load_memory: bool = True
    synthesize: bool = True
    play: bool = True
    one_shot: bool = False
    device_index: int | None = None
    wake_word_model: str = DEFAULT_WAKE_WORD_MODEL
    wake_word_threshold: float = DEFAULT_WAKE_WORD_THRESHOLD
    download_wake_models: bool = False
    vad_max_wait_s: int = DEFAULT_MAX_WAIT_S

    def __post_init__(self) -> None:
        if self.wake_word_threshold < 0:
            raise ValueError("wake_word_threshold must not be negative.")
        if self.vad_max_wait_s <= 0:
            raise ValueError("vad_max_wait_s must be positive.")
        if self.play and not self.synthesize:
            raise ValueError("play requires synthesize.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the live local app loop from the command line."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = _config_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        run_live_app(config)
    except ReasoningConfigurationError as exc:
        print(f"Live app reasoning configuration error: {exc}", file=sys.stderr)
        return 2
    except (ReasoningBackendUnavailableError, ReasoningModelUnavailableError) as exc:
        print(f"Live app reasoning unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


def run_live_app(
    config: LiveAppConfig | None = None,
    *,
    app_pipeline: VoiceConciergePipeline | None = None,
    wake_word_listener: WakeWordListener | None = None,
    utterance_capturer: UtteranceCapturer | None = None,
    stdout: TextIO = sys.stdout,
) -> AppPipelineState:
    """Run the live voice loop and return the final in-process app state."""

    runtime_config = config or LiveAppConfig()
    pipeline = app_pipeline or build_live_app_pipeline(runtime_config)
    owns_pipeline = app_pipeline is None
    capturer = utterance_capturer or build_utterance_capturer(runtime_config)
    state = AppPipelineState()

    def handle_audio(audio: CapturedAudio) -> None:
        nonlocal state
        result = pipeline.process_audio(
            audio,
            state,
            synthesize=runtime_config.synthesize,
            play=runtime_config.play,
        )
        state = result.state
        _print_turn_result(result, stdout=stdout)

    try:
        if runtime_config.use_wake_word:
            listener = wake_word_listener or build_wake_word_listener(runtime_config)
            _run_wake_word_loop(
                listener,
                capturer,
                on_utterance=handle_audio,
                one_shot=runtime_config.one_shot,
                stdout=stdout,
            )
        else:
            _run_vad_only_loop(
                capturer,
                on_utterance=handle_audio,
                one_shot=runtime_config.one_shot,
                stdout=stdout,
            )
    except KeyboardInterrupt:
        print("\nLive app stopped.", file=stdout)
    finally:
        if owns_pipeline:
            pipeline.close()

    return state


def build_live_app_pipeline(config: LiveAppConfig) -> VoiceConciergePipeline:
    """Build the app pipeline with the real local voice dependencies."""

    from voice_concierge.audio.player import SoundDevicePlayer
    from voice_concierge.voice_input.stt.factory import build_speech_to_text
    from voice_concierge.voice_output.factory import build_text_to_speech

    text_to_speech = build_text_to_speech() if config.synthesize else None
    audio_player = SoundDevicePlayer() if config.play else None
    return build_voice_concierge_pipeline(
        speech_to_text=build_speech_to_text(),
        text_to_speech=text_to_speech,
        audio_player=audio_player,
        load_memory=config.load_memory,
    )


def build_wake_word_listener(config: LiveAppConfig) -> WakeWordListener:
    """Build the configured wake-word listener for the live loop."""

    return WakeWordDetector(
        model_name=config.wake_word_model,
        confidence_threshold=config.wake_word_threshold,
        download_models=config.download_wake_models,
        audio_source=PyAudioSource(
            rate=DEFAULT_RATE,
            frames_per_buffer=DEFAULT_WAKE_WORD_CHUNK,
            input_device_index=config.device_index,
        ),
    )


def build_utterance_capturer(config: LiveAppConfig) -> UtteranceCapturer:
    """Build the configured VAD utterance capturer for the live loop."""

    return VoiceActivityDetector(
        max_wait_s=config.vad_max_wait_s,
        audio_source=PyAudioSource(
            rate=DEFAULT_RATE,
            frames_per_buffer=DEFAULT_VAD_CHUNK,
            input_device_index=config.device_index,
        ),
    )


def _run_wake_word_loop(
    listener: WakeWordListener,
    capturer: UtteranceCapturer,
    *,
    on_utterance: Callable[[CapturedAudio], None],
    one_shot: bool,
    stdout: TextIO,
) -> None:
    print("Live app started. Say the wake phrase to begin.", file=stdout)
    while True:
        listener.listen(
            on_wake_word=lambda: capturer.capture_utterance(
                on_utterance_captured=on_utterance
            )
        )
        if one_shot:
            break


def _run_vad_only_loop(
    capturer: UtteranceCapturer,
    *,
    on_utterance: Callable[[CapturedAudio], None],
    one_shot: bool,
    stdout: TextIO,
) -> None:
    print("Live app started without wake word. Speak a command.", file=stdout)
    while True:
        capturer.capture_utterance(on_utterance_captured=on_utterance)
        if one_shot:
            break


def _print_turn_result(result: AppTurnResult, *, stdout: TextIO) -> None:
    transcript = result.transcript.text if result.transcript is not None else ""
    print(f"You: {transcript or '<not transcribed>'}", file=stdout)
    print(f"Assistant: {result.spoken_response}", file=stdout)
    print(f"Mode: {result.state.context.mode}", file=stdout)
    if result.errors:
        print(f"Errors: {', '.join(result.errors)}", file=stdout)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run wake word -> VAD -> STT -> app pipeline -> TTS locally.",
    )
    parser.add_argument(
        "--no-wake-word",
        action="store_true",
        help="Skip wake word detection and repeatedly capture speech with VAD.",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="Optional PyAudio input device index for wake word and VAD capture.",
    )
    parser.add_argument(
        "--wake-model",
        default=DEFAULT_WAKE_WORD_MODEL,
        help="openWakeWord model filename or path.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_WAKE_WORD_THRESHOLD,
        help="Wake-word confidence threshold.",
    )
    parser.add_argument(
        "--download-wake-models",
        action="store_true",
        help="Allow openWakeWord to download model resources on startup.",
    )
    parser.add_argument(
        "--vad-max-wait-s",
        type=int,
        default=DEFAULT_MAX_WAIT_S,
        help="Seconds VAD waits for speech after wake/no-wake listening starts.",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable persistent local memory for this run.",
    )
    parser.add_argument(
        "--no-playback",
        action="store_true",
        help="Synthesize response audio but do not play it through speakers.",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Disable TTS synthesis and speaker playback.",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Handle one wake/capture attempt and exit.",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> LiveAppConfig:
    synthesize = not args.no_tts
    play = synthesize and not args.no_playback
    return LiveAppConfig(
        use_wake_word=not args.no_wake_word,
        load_memory=not args.no_memory,
        synthesize=synthesize,
        play=play,
        one_shot=args.one_shot,
        device_index=args.device_index,
        wake_word_model=args.wake_model,
        wake_word_threshold=args.threshold,
        download_wake_models=args.download_wake_models,
        vad_max_wait_s=args.vad_max_wait_s,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
