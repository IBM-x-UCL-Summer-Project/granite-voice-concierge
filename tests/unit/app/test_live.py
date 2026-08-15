"""Tests for the live app runner control flow."""

from __future__ import annotations

import io

import numpy as np
import pytest

from voice_concierge.app import live
from voice_concierge.app.types import AppPipelineState, AppTranscript, AppTurnResult
from voice_concierge.audio import CapturedAudio
from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import ContextDecision


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.close_count = 0

    def process_audio(
        self,
        audio: CapturedAudio,
        state: AppPipelineState | None = None,
        *,
        synthesize: bool = False,
        play: bool = False,
    ) -> AppTurnResult:
        self.calls.append(
            {
                "audio": audio,
                "state": state,
                "synthesize": synthesize,
                "play": play,
            }
        )
        next_state = AppPipelineState(last_spoken_response="fake response")
        return AppTurnResult(
            state=next_state,
            spoken_response="fake response",
            context_decision=ContextDecision(
                state=next_state.context,
                policy=policy_for_mode(
                    next_state.context.mode,
                    next_state.context.accessibility,
                ),
            ),
            transcript=AppTranscript(text="turn transcript"),
        )

    def close(self) -> None:
        self.close_count += 1


class FakeWakeWordListener:
    def __init__(self) -> None:
        self.listen_count = 0

    def listen(self, on_wake_word) -> None:
        self.listen_count += 1
        on_wake_word()


class FakeUtteranceCapturer:
    def __init__(self) -> None:
        self.capture_count = 0

    def capture_utterance(self, on_utterance_captured) -> None:
        self.capture_count += 1
        on_utterance_captured(_audio())


def test_run_live_app_with_wake_word_processes_one_turn() -> None:
    pipeline = FakePipeline()
    listener = FakeWakeWordListener()
    capturer = FakeUtteranceCapturer()
    stdout = io.StringIO()

    state = live.run_live_app(
        live.LiveAppConfig(one_shot=True, play=False),
        app_pipeline=pipeline,  # type: ignore[arg-type]
        wake_word_listener=listener,
        utterance_capturer=capturer,
        stdout=stdout,
    )

    assert listener.listen_count == 1
    assert capturer.capture_count == 1
    assert pipeline.close_count == 0
    assert pipeline.calls[0]["synthesize"] is True
    assert pipeline.calls[0]["play"] is False
    assert state.last_spoken_response == "fake response"
    assert "You: turn transcript" in stdout.getvalue()
    assert "Assistant: fake response" in stdout.getvalue()


def test_run_live_app_without_wake_word_uses_vad_only() -> None:
    pipeline = FakePipeline()
    capturer = FakeUtteranceCapturer()

    live.run_live_app(
        live.LiveAppConfig(
            use_wake_word=False,
            one_shot=True,
            synthesize=False,
            play=False,
        ),
        app_pipeline=pipeline,  # type: ignore[arg-type]
        utterance_capturer=capturer,
        stdout=io.StringIO(),
    )

    assert capturer.capture_count == 1
    assert pipeline.calls[0]["synthesize"] is False
    assert pipeline.calls[0]["play"] is False


def test_owned_pipeline_is_closed(monkeypatch) -> None:
    pipeline = FakePipeline()
    monkeypatch.setattr(live, "build_live_app_pipeline", lambda config: pipeline)

    live.run_live_app(
        live.LiveAppConfig(use_wake_word=False, one_shot=True, play=False),
        utterance_capturer=FakeUtteranceCapturer(),
        stdout=io.StringIO(),
    )

    assert pipeline.close_count == 1


def test_config_from_args_maps_live_options() -> None:
    args = live._build_parser().parse_args(
        [
            "--no-wake-word",
            "--device-index",
            "2",
            "--threshold",
            "0.2",
            "--no-memory",
            "--no-playback",
            "--one-shot",
        ]
    )

    config = live._config_from_args(args)

    assert config.use_wake_word is False
    assert config.device_index == 2
    assert config.wake_word_threshold == 0.2
    assert config.load_memory is False
    assert config.synthesize is True
    assert config.play is False
    assert config.one_shot is True


def test_config_from_args_no_tts_disables_playback() -> None:
    args = live._build_parser().parse_args(["--no-tts"])

    config = live._config_from_args(args)

    assert config.synthesize is False
    assert config.play is False


def test_config_rejects_play_without_synthesis() -> None:
    with pytest.raises(ValueError, match="play requires synthesize"):
        live.LiveAppConfig(synthesize=False, play=True)


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(1280, dtype=np.int16),
        sample_rate=16000,
        channels=1,
    )


class _FakeStt:
    """Speech-to-text stub for the guided-routine gate."""

    def __init__(self, text: str = "", *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail

    def transcribe(self, audio: CapturedAudio):
        if self._fail:
            raise RuntimeError("stt exploded")
        return AppTranscript(text=self._text)


class _RoutinePipeline(FakePipeline):
    """Pipeline exposing a speech_to_text, as the real one does."""

    def __init__(self, stt=None) -> None:
        super().__init__()
        self.speech_to_text = stt


class _FakeRoutines:
    """Routine handler stub recording what it was asked to run."""

    def __init__(self, *, handles: bool = True) -> None:
        self._handles = handles
        self.ran: list[str] = []

    def handles(self, transcript: str) -> bool:
        return self._handles

    def run(self, transcript: str) -> str:
        self.ran.append(transcript)
        return "Routine finished."


def _run_one_turn(pipeline, routines, stdout):
    return live.run_live_app(
        live.LiveAppConfig(
            use_wake_word=False, one_shot=True, synthesize=False, play=False
        ),
        app_pipeline=pipeline,
        utterance_capturer=FakeUtteranceCapturer(),
        routine_handler=routines,
        stdout=stdout,
    )


def test_guidance_request_is_routed_to_the_routine_handler() -> None:
    pipeline = _RoutinePipeline(_FakeStt("guide me through making tea"))
    routines = _FakeRoutines()
    stdout = io.StringIO()

    _run_one_turn(pipeline, routines, stdout)

    assert routines.ran == ["guide me through making tea"]
    assert pipeline.calls == []  # the ordinary reasoning turn was skipped
    assert "Routine finished." in stdout.getvalue()


def test_ordinary_request_still_runs_the_normal_turn() -> None:
    pipeline = _RoutinePipeline(_FakeStt("what is the weather"))
    routines = _FakeRoutines(handles=False)

    _run_one_turn(pipeline, routines, io.StringIO())

    assert routines.ran == []
    assert len(pipeline.calls) == 1


def test_failed_transcription_falls_back_to_the_normal_turn() -> None:
    """The pipeline reports the STT failure itself; the turn is not lost."""
    pipeline = _RoutinePipeline(_FakeStt(fail=True))
    routines = _FakeRoutines()

    _run_one_turn(pipeline, routines, io.StringIO())

    assert routines.ran == []
    assert len(pipeline.calls) == 1


def test_empty_transcript_falls_back_to_the_normal_turn() -> None:
    pipeline = _RoutinePipeline(_FakeStt("   "))
    routines = _FakeRoutines()

    _run_one_turn(pipeline, routines, io.StringIO())

    assert routines.ran == []
    assert len(pipeline.calls) == 1


def test_pipeline_without_stt_falls_back_to_the_normal_turn() -> None:
    pipeline = _RoutinePipeline(None)
    routines = _FakeRoutines()

    _run_one_turn(pipeline, routines, io.StringIO())

    assert routines.ran == []
    assert len(pipeline.calls) == 1


def test_unavailable_routine_stack_leaves_the_turn_ordinary(monkeypatch) -> None:
    """When routines cannot be built the app still answers normally."""
    monkeypatch.setattr(live, "build_routine_turn_handler", lambda config: None)
    pipeline = _RoutinePipeline(_FakeStt("guide me through making tea"))

    _run_one_turn(pipeline, None, io.StringIO())

    assert len(pipeline.calls) == 1


def test_routine_stack_is_built_only_for_a_guidance_request(monkeypatch) -> None:
    """Models must not load for someone who never asks to be guided."""
    builds: list[str] = []

    def _build(config):
        builds.append("built")
        return None

    monkeypatch.setattr(live, "build_routine_turn_handler", _build)
    _run_one_turn(
        _RoutinePipeline(_FakeStt("what is the weather")), None, io.StringIO()
    )

    assert builds == []


def test_disabling_guided_routines_skips_the_gate(monkeypatch) -> None:
    builds: list[str] = []
    monkeypatch.setattr(
        live, "build_routine_turn_handler", lambda config: builds.append("x")
    )
    pipeline = _RoutinePipeline(_FakeStt("guide me through making tea"))

    live.run_live_app(
        live.LiveAppConfig(
            use_wake_word=False,
            one_shot=True,
            synthesize=False,
            play=False,
            guided_routines=False,
        ),
        app_pipeline=pipeline,
        utterance_capturer=FakeUtteranceCapturer(),
        stdout=io.StringIO(),
    )

    assert builds == []
    assert len(pipeline.calls) == 1


def test_guided_routines_can_be_disabled_from_the_command_line() -> None:
    config = live._config_from_args(
        live._build_parser().parse_args(["--no-guided-routines"])
    )

    assert config.guided_routines is False


def test_guided_routines_are_on_by_default() -> None:
    config = live._config_from_args(live._build_parser().parse_args([]))

    assert config.guided_routines is True


class _CountingStt(_FakeStt):
    """Records how many times a turn was transcribed."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.calls = 0

    def transcribe(self, audio: CapturedAudio):
        self.calls += 1
        return super().transcribe(audio)


class _FullPipeline(_RoutinePipeline):
    """Pipeline exposing process_transcript, as the real one does."""

    def __init__(self, stt=None) -> None:
        super().__init__(stt)
        self.transcript_calls: list[str] = []

    def process_transcript(
        self, transcript, state=None, *, synthesize=False, play=False
    ):
        self.transcript_calls.append(transcript)
        return self.process_audio(_audio(), state, synthesize=synthesize, play=play)


def test_ordinary_turn_reuses_the_gate_transcript() -> None:
    """Speech is transcribed once per turn, not once per code path."""
    stt = _CountingStt("what is the weather")
    pipeline = _FullPipeline(stt)

    _run_one_turn(pipeline, None, io.StringIO())

    assert stt.calls == 1  # not transcribed a second time by the pipeline
    assert pipeline.transcript_calls == ["what is the weather"]


def test_falls_back_to_process_audio_without_process_transcript() -> None:
    """A pipeline stand-in lacking process_transcript still works."""
    pipeline = _RoutinePipeline(_FakeStt("what is the weather"))

    _run_one_turn(pipeline, None, io.StringIO())

    assert len(pipeline.calls) == 1


def test_unusable_transcript_falls_back_to_process_audio() -> None:
    """With no transcript to reuse, the pipeline handles the raw audio."""
    pipeline = _FullPipeline(_FakeStt(fail=True))

    _run_one_turn(pipeline, None, io.StringIO())

    assert pipeline.transcript_calls == []
    assert len(pipeline.calls) == 1


class _FakeReminders:
    """Reminder handler stub recording what it was asked to run."""

    def __init__(self, *, handles: bool = True) -> None:
        self._handles = handles
        self.ran: list[str] = []

    def handles(self, transcript: str) -> bool:
        return self._handles

    def run(self, transcript: str) -> str:
        self.ran.append(transcript)
        return "Timer set for 10 minutes."


def _run_reminder_turn(pipeline, reminders, stdout, *, config=None):
    return live.run_live_app(
        config
        or live.LiveAppConfig(
            use_wake_word=False, one_shot=True, synthesize=False, play=False
        ),
        app_pipeline=pipeline,
        utterance_capturer=FakeUtteranceCapturer(),
        reminder_handler=reminders,
        stdout=stdout,
    )


def test_a_reminder_request_is_routed_to_the_reminder_handler() -> None:
    pipeline = _RoutinePipeline(_FakeStt("remind me to stretch in 10 minutes"))
    reminders = _FakeReminders()
    stdout = io.StringIO()

    _run_reminder_turn(pipeline, reminders, stdout)

    assert reminders.ran == ["remind me to stretch in 10 minutes"]
    assert pipeline.calls == []  # the ordinary reasoning turn was skipped
    assert "Timer set for 10 minutes." in stdout.getvalue()


def test_an_ordinary_turn_is_not_routed_to_reminders() -> None:
    pipeline = _RoutinePipeline(_FakeStt("what is the weather"))
    reminders = _FakeReminders()

    _run_reminder_turn(pipeline, reminders, io.StringIO())

    assert reminders.ran == []
    assert len(pipeline.calls) == 1


def test_an_unavailable_reminder_stack_falls_back_to_a_normal_turn(
    monkeypatch,
) -> None:
    """A reminder store that cannot open must not cost the user their turn."""
    monkeypatch.setattr(live, "build_reminder_turn_handler", lambda config: None)
    monkeypatch.setattr(live, "_start_reminder_runner", lambda *a, **k: None)
    pipeline = _RoutinePipeline(_FakeStt("remind me to stretch in 10 minutes"))

    _run_reminder_turn(pipeline, None, io.StringIO())

    assert len(pipeline.calls) == 1


def test_disabling_reminders_leaves_the_turn_ordinary(monkeypatch) -> None:
    builds: list[str] = []
    monkeypatch.setattr(
        live, "build_reminder_turn_handler", lambda config: builds.append("x")
    )
    monkeypatch.setattr(live, "_start_reminder_runner", lambda *a, **k: None)
    pipeline = _RoutinePipeline(_FakeStt("remind me to stretch in 10 minutes"))

    _run_reminder_turn(
        pipeline,
        None,
        io.StringIO(),
        config=live.LiveAppConfig(
            use_wake_word=False,
            one_shot=True,
            synthesize=False,
            play=False,
            reminders=False,
            guided_routines=False,
        ),
    )

    assert builds == []
    assert len(pipeline.calls) == 1


def test_reminders_can_be_disabled_from_the_command_line() -> None:
    config = live._config_from_args(live._build_parser().parse_args(["--no-reminders"]))

    assert config.reminders is False


def test_reminders_are_on_by_default() -> None:
    assert live._config_from_args(live._build_parser().parse_args([])).reminders is True
