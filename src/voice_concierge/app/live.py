"""Live local E2E runner for the app pipeline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from voice_concierge.app.factory import build_voice_concierge_pipeline
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reminders import (
    CANCEL_ALL_PHRASES,
    LIST_PHRASES,
    ReminderTurnHandler,
    SpokenNotifier,
)
from voice_concierge.app.routines import RoutineTurnHandler
from voice_concierge.app.types import AppPipelineState, AppTurnResult
from voice_concierge.audio import CapturedAudio, PyAudioSource
from voice_concierge.reasoning.errors import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelUnavailableError,
)
from voice_concierge.routines.intent import is_routine_request
from voice_concierge.scheduling.parser import is_reminder_request
from voice_concierge.scheduling.runner import ReminderRunner
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
    guided_routines: bool = True
    reminders: bool = True
    one_breath: bool = False

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
    routine_handler: RoutineTurnHandler | None = None,
    reminder_handler: ReminderTurnHandler | None = None,
    stdout: TextIO = sys.stdout,
) -> AppPipelineState:
    """Run the live voice loop and return the final in-process app state."""

    runtime_config = config or LiveAppConfig()
    pipeline = app_pipeline or build_live_app_pipeline(runtime_config)
    owns_pipeline = app_pipeline is None
    capturer = utterance_capturer or build_utterance_capturer(runtime_config)
    state = AppPipelineState()
    routines = routine_handler
    resolved_routines = routines is not None
    reminders = reminder_handler
    owns_reminders = reminder_handler is None
    resolved_reminders = reminders is not None

    def get_routines() -> RoutineTurnHandler | None:
        """Build the routine stack on first use, then reuse it.

        Deferred because it loads a recognizer and a reasoning backend: a user
        who never asks to be walked through anything should never pay for them,
        and neither should a caller embedding this runner.
        """
        nonlocal routines, resolved_routines
        if not resolved_routines:
            routines = build_routine_turn_handler(runtime_config)
            resolved_routines = True
        return routines

    def get_reminders() -> ReminderTurnHandler | None:
        """Build the reminder stack on first use, then reuse it."""
        nonlocal reminders, resolved_reminders
        if not resolved_reminders:
            reminders = build_reminder_turn_handler(runtime_config)
            resolved_reminders = True
        return reminders

    def handle_audio(audio: CapturedAudio) -> None:
        nonlocal state
        # A guided routine takes over the conversation for many turns, so it is
        # routed before reasoning; everything else is an ordinary turn.
        gate = _gate_turn(runtime_config, pipeline, audio)
        if gate.is_routine and gate.transcript is not None:
            handler = get_routines()
            if handler is not None:
                print(f"You: {gate.transcript}", file=stdout)
                print(handler.run(gate.transcript), file=stdout)
                return
        if gate.is_reminder and gate.transcript is not None:
            handler = get_reminders()
            if handler is not None:
                print(f"You: {gate.transcript}", file=stdout)
                print(f"Assistant: {handler.run(gate.transcript)}", file=stdout)
                return
        result = _process_turn(pipeline, audio, gate, state, runtime_config)
        state = result.state
        _print_turn_result(result, stdout=stdout)

    runner = _start_reminder_runner(runtime_config, pipeline, get_reminders, stdout)
    try:
        if runtime_config.use_wake_word and runtime_config.one_breath:
            _run_one_breath_loop(
                build_one_breath_capturer(runtime_config),
                on_utterance=handle_audio,
                one_shot=runtime_config.one_shot,
                stdout=stdout,
            )
        elif runtime_config.use_wake_word:
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
        if runner is not None:
            runner.stop()
        if owns_reminders and reminders is not None:
            reminders.close()
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

    speech_to_text = build_speech_to_text()
    if config.one_breath:
        # The retained audio carries the wake phrase, so take it back off the
        # transcript before anything tries to match on the whole utterance.
        from voice_concierge.app.one_breath import WakePhraseStrippingSpeechToText

        speech_to_text = WakePhraseStrippingSpeechToText(speech_to_text)

    return build_voice_concierge_pipeline(
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
        audio_player=audio_player,
        load_memory=config.load_memory,
    )


@dataclass(frozen=True)
class _GatedTurn:
    """What the guided-routine gate learned about one captured turn."""

    #: The transcript, or None when speech recognition gave nothing usable.
    transcript: str | None
    #: True when the transcript is asking to be walked through something.
    is_routine: bool
    #: True when the transcript is about reminders or timers.
    is_reminder: bool = False


def _gate_turn(
    config: LiveAppConfig,
    pipeline: VoiceConciergePipeline,
    audio: CapturedAudio,
) -> _GatedTurn:
    """Transcribe the turn and decide whether it should run as a routine.

    Deciding this costs the transcription the turn needs anyway plus a phrase
    match, so no model is loaded to answer it, and the transcript is handed back
    so the ordinary path can reuse it rather than transcribing a second time.
    A missing or failing recognizer yields no transcript, which sends the turn
    down the ordinary path where the pipeline reports the failure itself.
    """
    if not (config.guided_routines or config.reminders):
        return _GatedTurn(None, False)
    # getattr: callers may inject a pipeline stand-in without this attribute.
    speech_to_text = getattr(pipeline, "speech_to_text", None)
    if speech_to_text is None:
        return _GatedTurn(None, False)
    try:
        transcript = speech_to_text.transcribe(audio).text.strip()
    except Exception:
        return _GatedTurn(None, False)
    if not transcript:
        return _GatedTurn(None, False)
    return _GatedTurn(
        transcript,
        config.guided_routines and is_routine_request(transcript),
        config.reminders and _reminder_intent(transcript),
    )


def _process_turn(
    pipeline: VoiceConciergePipeline,
    audio: CapturedAudio,
    gate: _GatedTurn,
    state: AppPipelineState,
    config: LiveAppConfig,
) -> AppTurnResult:
    """Run one ordinary turn, reusing a transcript the gate already produced.

    Transcription is the most expensive step of a turn, so when the gate has
    already run it the text goes straight to the pipeline. Falls back to
    process_audio when the gate produced nothing, and when a caller injected a
    pipeline stand-in that has no process_transcript.
    """
    process_transcript = getattr(pipeline, "process_transcript", None)
    if gate.transcript is not None and process_transcript is not None:
        return process_transcript(
            gate.transcript,
            state,
            synthesize=config.synthesize,
            play=config.play,
        )
    return pipeline.process_audio(
        audio, state, synthesize=config.synthesize, play=config.play
    )


def _reminder_intent(transcript: str) -> bool:
    """True when the transcript is about reminders or timers.

    Kept here rather than on the handler so the gate can decide without building
    the reminder stack, which is what keeps the models unloaded for a user who
    never sets one.
    """
    lowered = transcript.casefold()
    return (
        is_reminder_request(transcript)
        or any(phrase in lowered for phrase in LIST_PHRASES)
        or any(phrase in lowered for phrase in CANCEL_ALL_PHRASES)
    )


def build_reminder_turn_handler(  # pragma: no cover - opens the local database
    config: LiveAppConfig,
) -> ReminderTurnHandler | None:
    """Assemble the reminder handler, or None if the store cannot be opened."""
    from voice_concierge.scheduling.factory import build_reminder_service

    if not config.reminders:
        return None
    try:
        return ReminderTurnHandler(build_reminder_service())
    except Exception:
        return None


def _start_reminder_runner(  # pragma: no cover - starts a background thread
    config: LiveAppConfig,
    pipeline: VoiceConciergePipeline,
    get_handler: Callable[[], ReminderTurnHandler | None],
    stdout: TextIO,
) -> ReminderRunner | None:
    """Start delivering due reminders in the background, if reminders are on.

    Anything already overdue, including reminders missed while the assistant was
    not running, is delivered on the first check rather than skipped.
    """
    if not config.reminders:
        return None
    handler = get_handler()
    if handler is None:
        return None
    service = getattr(handler, "service", None)
    if service is None:
        return None
    notifier = SpokenNotifier(
        pipeline.text_to_speech if config.play else None,
        pipeline.audio_player if config.play else None,
        write=lambda line: print(line, file=stdout),
    )
    runner = ReminderRunner(service, notifier)
    runner.start()
    return runner


def build_routine_turn_handler(  # pragma: no cover - builds models and devices
    config: LiveAppConfig,
) -> RoutineTurnHandler | None:
    """Assemble the guided-routine handler, or None if it cannot be built.

    Guided routines need echo-cancelled playback (macOS only today) and the
    reasoning backend. When either is missing this returns None rather than
    raising, so the app still starts and simply answers normally.
    """
    from voice_concierge.app.routines import (
        EchoCancelledStepSpeaker,
        MicCommandWaiter,
    )
    from voice_concierge.audio.voice_processing_player import (
        VoiceProcessingAudioPlayer,
        echo_cancellation_available,
    )
    from voice_concierge.command_control import (
        StableCommandSpotter,
        build_vosk_command_spotter,
    )
    from voice_concierge.memory import build_memory_manager
    from voice_concierge.reasoning.factory import build_reasoning_engine
    from voice_concierge.routines import RoutineRunner, build_routine_adapter
    from voice_concierge.voice_output.factory import build_paced_text_to_speech

    if not echo_cancellation_available():
        # Without echo cancellation the assistant hears its own speech as a
        # command, so a guided routine would fight itself. Answer normally.
        return None
    try:
        adapter = build_routine_adapter(
            memory_manager=build_memory_manager(),
            reasoning_engine=build_reasoning_engine(),
        )
        # One shared vocabulary spots playback and routine words; the stabilizer
        # keeps a partial-result recognizer from firing twice or on noise.
        spotter = StableCommandSpotter(build_vosk_command_spotter())
        player = VoiceProcessingAudioPlayer()
        # A paced voice, so "slower" and "faster" spoken during a step
        # change the rate and have the step read again at the new speed.
        paced = build_paced_text_to_speech()
        speaker = EchoCancelledStepSpeaker(paced, player, spotter, pace=paced)
        waiter = MicCommandWaiter(
            PyAudioSource(rate=DEFAULT_RATE, input_device_index=config.device_index),
            spotter,
        )
    except Exception:
        return None
    return RoutineTurnHandler(adapter, RoutineRunner(adapter, speaker, waiter))


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


def build_one_breath_capturer(config: LiveAppConfig):  # pragma: no cover - devices
    """Build a capturer that holds one stream across both capture stages.

    Keeping the device open is what lets a whole sentence spoken in one breath
    survive: the separate wake-word and VAD components each own a stream, and
    the handoff between them costs exactly the words after the wake phrase.
    """
    # Local
    from voice_concierge.voice_input.one_breath import OneBreathCapturer
    from voice_concierge.voice_input.one_breath_models import (
        OpenWakeWordSpotter,
        SileroSpeechGate,
    )

    source = PyAudioSource(
        rate=DEFAULT_RATE,
        frames_per_buffer=DEFAULT_WAKE_WORD_CHUNK,
        input_device_index=config.device_index,
    )
    source.open()
    return OneBreathCapturer(
        audio_source=source,
        spotter=OpenWakeWordSpotter(
            model_name=config.wake_word_model,
            confidence_threshold=config.wake_word_threshold,
            download_models=config.download_wake_models,
        ),
        speech_gate=SileroSpeechGate(rate=DEFAULT_RATE),
        chunk=DEFAULT_WAKE_WORD_CHUNK,
        rate=DEFAULT_RATE,
        utterance_timeout_s=float(config.vad_max_wait_s),
    )


def _run_one_breath_loop(
    capturer,
    *,
    on_utterance: Callable[[CapturedAudio], None],
    one_shot: bool,
    stdout: TextIO,
) -> None:
    print(
        "Live app started. Say the wake phrase and your request together.",
        file=stdout,
    )
    while True:
        capturer.capture_utterance(on_utterance_captured=on_utterance)
        if one_shot:
            break


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
    if result.memory_operation.outcome is not None:
        outcome = result.memory_operation.outcome
        diagnostic = outcome.status.value
        if outcome.detail is not None:
            diagnostic = f"{diagnostic} ({outcome.detail})"
        print(f"Memory operation: {diagnostic}", file=stdout)


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
    parser.add_argument(
        "--no-reminders",
        action="store_true",
        help="Disable local reminders and timers.",
    )
    parser.add_argument(
        "--no-guided-routines",
        action="store_true",
        help="Answer step-by-step requests normally instead of guiding them.",
    )
    parser.add_argument(
        "--one-breath",
        action="store_true",
        help=(
            "Hold one microphone stream across wake word and capture, so the "
            "wake phrase and request can be said in a single sentence."
        ),
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
        guided_routines=not args.no_guided_routines,
        reminders=not args.no_reminders,
        one_breath=args.one_breath,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
