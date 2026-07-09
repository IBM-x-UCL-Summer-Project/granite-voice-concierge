"""Tests for the framework-free app turn adapter."""

from __future__ import annotations

from voice_concierge.app.adapter import handle_turn
from voice_concierge.app.reasoning import ReasoningTurnResult
from voice_concierge.app.serialization import app_pipeline_state_to_dict
from voice_concierge.app.types import AppPipelineState, AppTurnRequest, AppTurnResult
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
