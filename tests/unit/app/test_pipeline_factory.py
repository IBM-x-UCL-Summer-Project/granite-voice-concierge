"""Tests for app pipeline factory helpers and public exports."""

from __future__ import annotations

from voice_concierge.app import (
    AppPipelineState,
    AppReasoningConfig,
    VoiceConciergePipeline,
    build_voice_concierge_pipeline,
)
from voice_concierge.app import factory as factory_module
from voice_concierge.app.memory import NullMemoryGateway
from voice_concierge.app.reasoning import ReasoningTurnContext, ReasoningTurnResult
from voice_concierge.memory import LocalMemoryConfig
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


def test_build_voice_concierge_pipeline_loads_configured_local_memory(
    monkeypatch,
    tmp_path,
) -> None:
    reasoning = FakeReasoning()
    memory = NullMemoryGateway()
    memory_config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memory.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
    )
    calls: list[LocalMemoryConfig | None] = []

    def fake_build_local_memory_gateway(
        supplied_config: LocalMemoryConfig | None = None,
    ) -> NullMemoryGateway:
        calls.append(supplied_config)
        return memory

    monkeypatch.setattr(
        factory_module,
        "build_local_memory_gateway",
        fake_build_local_memory_gateway,
    )

    pipeline = build_voice_concierge_pipeline(
        reasoning_service=reasoning,
        memory_config=memory_config,
        load_memory=True,
    )

    assert isinstance(pipeline, VoiceConciergePipeline)
    assert calls == [memory_config]


def test_build_voice_concierge_pipeline_keeps_memory_unloaded_by_default(
    monkeypatch,
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("local memory should remain unloaded")

    monkeypatch.setattr(
        factory_module,
        "build_local_memory_gateway",
        fail_if_called,
    )

    pipeline = build_voice_concierge_pipeline(reasoning_service=FakeReasoning())

    assert isinstance(pipeline, VoiceConciergePipeline)
