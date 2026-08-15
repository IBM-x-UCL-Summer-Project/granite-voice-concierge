"""Integration coverage for persistent memory in the app pipeline."""

from __future__ import annotations

import pytest

from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import (
    ReasoningTurnContext,
    ReasoningTurnResult,
)
from voice_concierge.memory import (
    LocalMemoryConfig,
    MemoryDecayPolicy,
    build_memory_manager,
)
from voice_concierge.reasoning.types import MemoryAction, ReasoningResponse


class DeterministicEmbeddingService:
    """Return a stable vector without requiring an Ollama embedding model."""

    def get_embedding(self, content: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class FailingValidator:
    """Prove confirmed app writes do not invoke secondary LLM classification."""

    def should_store(self, content: str):
        raise AssertionError("confirmed writes should not be revalidated")

    def classify_memory_type(self, content: str):
        raise AssertionError("confirmed writes should not be classified")

    def extract_metadata(self, content: str):
        raise AssertionError("confirmed writes should not extract metadata")


class FailingEmbeddingService:
    def get_embedding(self, content: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


class ProposalReasoning:
    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response=(
                    "I can remember that. Please confirm before I save it."
                ),
                needs_confirmation=True,
                proposed_memory_action=MemoryAction(
                    action="store",
                    content="User prefers tea.",
                    rationale="User asked the assistant to remember it.",
                ),
                confidence="high",
            )
        )


class RecallReasoning:
    def __init__(self) -> None:
        self.contexts: list[ReasoningTurnContext | None] = []

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        self.contexts.append(context)
        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response="You prefer tea.",
                confidence="high",
            )
        )


def test_local_memory_config_injects_decay_policy(tmp_path) -> None:
    decay_policy = MemoryDecayPolicy(
        base_half_life_days=14,
        minimum_retention=0.25,
        retrieval_weight=0.6,
    )
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memories.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
        embedding_dimension=4,
        decay_policy=decay_policy,
    )

    manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )

    try:
        assert manager.retriever.decay_policy is decay_policy
    finally:
        manager.close()


@pytest.mark.integration
def test_confirmed_memory_survives_reopen_and_reaches_reasoning(tmp_path) -> None:
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "nested" / "memories.sqlite3",
        vector_db_path=tmp_path / "nested" / "vectors.sqlite3",
        embedding_dimension=4,
    )
    manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    pipeline = VoiceConciergePipeline(
        ProposalReasoning(),
        memory=MemoryManagerGateway(manager),
    )

    proposal = pipeline.process_transcript("remember that I prefer tea")
    confirmation = pipeline.process_transcript("yes", proposal.state)

    assert confirmation.memory_operation.attempted is True
    assert confirmation.memory_operation.succeeded is True
    assert confirmation.memory_operation.reason == "stored_successfully"
    assert confirmation.errors == ()
    pipeline.close()

    recall_reasoning = RecallReasoning()
    reopened_manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    reopened_pipeline = VoiceConciergePipeline(
        recall_reasoning,
        memory=MemoryManagerGateway(reopened_manager),
    )

    try:
        recall = reopened_pipeline.process_transcript(
            "what do you remember",
            confirmation.state,
        )
    finally:
        reopened_pipeline.close()

    assert recall.errors == ()
    assert recall_reasoning.contexts
    context = recall_reasoning.contexts[0]
    assert context is not None
    assert context.memories == ("User prefers tea.",)


@pytest.mark.integration
def test_failed_embedding_rolls_back_confirmed_memory_record(tmp_path) -> None:
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memories.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
        embedding_dimension=4,
    )
    manager = build_memory_manager(
        config,
        embedding_service=FailingEmbeddingService(),
        validator=FailingValidator(),
    )
    pipeline = VoiceConciergePipeline(
        ProposalReasoning(),
        memory=MemoryManagerGateway(manager),
    )

    try:
        proposal = pipeline.process_transcript("remember that I prefer tea")
        confirmation = pipeline.process_transcript("yes", proposal.state)

        assert confirmation.memory_operation.attempted is True
        assert confirmation.memory_operation.succeeded is False
        assert confirmation.errors == ("memory_action_failed",)
        assert manager.get_all_memories() == []
    finally:
        pipeline.close()
