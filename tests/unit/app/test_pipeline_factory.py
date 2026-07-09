"""Tests for app pipeline factory helpers and public exports."""

from __future__ import annotations

from voice_concierge.app import (
    AppPipelineState,
    AppReasoningConfig,
    VoiceConciergePipeline,
    build_voice_concierge_pipeline,
)
from voice_concierge.app import factory as factory_module
from voice_concierge.app.reasoning import ReasoningTurnContext, ReasoningTurnResult
from voice_concierge.reasoning.types import ReasoningResponse


class FakeReasoning:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        self.calls.append({"transcript": transcript, "context": context})
        return ReasoningTurnResult(
            response=ReasoningResponse(spoken_response="Factory response.")
        )


def test_build_voice_concierge_pipeline_uses_injected_reasoning_service() -> None:
    reasoning = FakeReasoning()

    pipeline = build_voice_concierge_pipeline(reasoning_service=reasoning)
    result = pipeline.process_transcript("hello")

    assert isinstance(pipeline, VoiceConciergePipeline)
    assert isinstance(result.state, AppPipelineState)
    assert result.spoken_response == "Factory response."
    assert reasoning.calls[0]["transcript"] == "hello"


def test_build_voice_concierge_pipeline_builds_reasoning_when_not_injected(
    monkeypatch,
) -> None:
    reasoning = FakeReasoning()
    config = AppReasoningConfig(timeout_s=7.5)
    calls: list[AppReasoningConfig | None] = []

    def fake_build_reasoning_turn_service(
        supplied_config: AppReasoningConfig | None = None,
    ) -> FakeReasoning:
        calls.append(supplied_config)
        return reasoning

    monkeypatch.setattr(
        factory_module,
        "build_reasoning_turn_service",
        fake_build_reasoning_turn_service,
    )

    pipeline = factory_module.build_voice_concierge_pipeline(config)
    result = pipeline.process_transcript("hello")

    assert result.spoken_response == "Factory response."
    assert calls == [config]
