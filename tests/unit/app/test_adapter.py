"""Tests for the framework-free app turn adapter."""

from __future__ import annotations

import base64

import numpy as np
import pytest

from voice_concierge.app.adapter import handle_audio_turn, handle_turn
from voice_concierge.app.reasoning import ReasoningTurnResult
from voice_concierge.app.serialization import (
    PayloadValidationError,
    app_pipeline_state_to_dict,
)
from voice_concierge.app.types import (
    AppPipelineState,
    AppTranscript,
    AppTurnRequest,
    AppTurnResult,
)
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import ContextDecision
from voice_concierge.reasoning.types import ReasoningResponse


class FakePipeline:
    def __init__(self) -> None:
        self.requests: list[AppTurnRequest] = []

    def process_request(self, request: AppTurnRequest) -> AppTurnResult:
        self.requests.append(request)
        state = AppPipelineState(last_spoken_response="Adapter response.")
        return AppTurnResult(
            state=state,
            spoken_response="Adapter response.",
            context_decision=ContextDecision(
                state=state.context,
                policy=policy_for_mode("home", state.context.accessibility),
            ),
            reasoning_result=ReasoningTurnResult(
                response=ReasoningResponse(spoken_response="Adapter response.")
            ),
        )


class FakeAudioPipeline(FakePipeline):
    def __init__(self) -> None:
        super().__init__()
        self.audio_calls: list[dict[str, object]] = []

    def process_audio(
        self,
        audio: CapturedAudio,
        state: AppPipelineState | None = None,
        *,
        synthesize: bool = False,
        play: bool = False,
    ) -> AppTurnResult:
        self.audio_calls.append(
            {
                "audio": audio,
                "state": state,
                "synthesize": synthesize,
                "play": play,
            }
        )
        next_state = AppPipelineState(last_spoken_response="Voice response.")
        return AppTurnResult(
            state=next_state,
            spoken_response="Voice response.",
            transcript=AppTranscript(text="voice request", language="en"),
            context_decision=ContextDecision(
                state=next_state.context,
                policy=policy_for_mode("home", next_state.context.accessibility),
            ),
        )


def test_handle_turn_parses_payload_processes_pipeline_and_serializes_result() -> None:
    pipeline = FakePipeline()
    state = AppPipelineState(last_spoken_response="Previous answer.")

    response = handle_turn(
        {
            "transcript": "hello",
            "state": app_pipeline_state_to_dict(state),
            "options": {
                "synthesize": False,
                "play": False,
            },
        },
        pipeline,
    )

    assert pipeline.requests == [
        AppTurnRequest(
            transcript="hello",
            state=state,
        )
    ]
    assert response["spoken_response"] == "Adapter response."
    assert response["state"]["last_spoken_response"] == "Adapter response."
    assert response["context"]["mode"] == "home"
    assert response["reasoning"]["confidence"] == "medium"


def test_handle_audio_turn_decodes_wav_and_uses_pipeline_audio_path() -> None:
    pipeline = FakeAudioPipeline()
    previous_state = AppPipelineState(last_spoken_response="Previous response.")
    audio = CapturedAudio(
        samples=np.array([0, 200, -200, 0], dtype=np.int16),
        sample_rate=16000,
    )

    response = handle_audio_turn(
        {
            "wav_base64": base64.b64encode(audio.to_wav_bytes()).decode("ascii"),
            "state": app_pipeline_state_to_dict(previous_state),
            "options": {"synthesize": True, "play": False},
        },
        pipeline,
    )

    call = pipeline.audio_calls[0]
    assert call["state"] == previous_state
    assert call["synthesize"] is True
    assert call["play"] is False
    assert call["audio"].sample_rate == 16000
    assert call["audio"].samples.tolist() == [0, 200, -200, 0]
    assert response["transcript"]["text"] == "voice request"
    assert response["spoken_response"] == "Voice response."


@pytest.mark.parametrize(
    "wav_base64",
    ["", "not base64", base64.b64encode(b"not a wav").decode("ascii")],
)
def test_handle_audio_turn_rejects_invalid_browser_audio(wav_base64: str) -> None:
    with pytest.raises(PayloadValidationError):
        handle_audio_turn({"wav_base64": wav_base64}, FakeAudioPipeline())
