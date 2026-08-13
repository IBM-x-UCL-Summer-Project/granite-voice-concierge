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
from voice_concierge.reasoning import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelUnavailableError,
)


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


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    (
        (
            ReasoningConfigurationError("bad selection"),
            2,
            "reasoning configuration error",
        ),
        (
            ReasoningBackendUnavailableError("runner unavailable"),
            1,
            "reasoning unavailable",
        ),
        (
            ReasoningModelUnavailableError("model unavailable"),
            1,
            "reasoning unavailable",
        ),
    ),
)
def test_main_maps_reasoning_startup_failures(
    monkeypatch,
    capsys,
    error: Exception,
    expected_code: int,
    expected_message: str,
) -> None:
    def fail_startup(config) -> None:
        raise error

    monkeypatch.setattr(live, "run_live_app", fail_startup)

    result = live.main(["--one-shot"])

    assert result == expected_code
    assert expected_message in capsys.readouterr().err


def _audio() -> CapturedAudio:
    return CapturedAudio(
        samples=np.zeros(1280, dtype=np.int16),
        sample_rate=16000,
        channels=1,
    )
