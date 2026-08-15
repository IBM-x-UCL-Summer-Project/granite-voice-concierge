"""Integration coverage for persistent memory in the app pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
    MemoryOperationStatus,
    build_memory_manager,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    ReasoningResponse,
    StructuredListOperation,
)


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


def test_memory_gateway_can_write_from_web_worker_thread(tmp_path) -> None:
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memories.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
        embedding_dimension=4,
    )
    manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content=None,
        rationale="User asked to add an item.",
        target=MemoryTarget(memory_key="list:shopping"),
        list_operation=StructuredListOperation(
            list_name="shopping",
            operation="add_items",
            items=("bananas",),
        ),
    )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                gateway.apply,
                action,
                "list_relevant",
            ).result()

        assert result.status is MemoryOperationStatus.STORED_SUCCESSFULLY
        shopping_list = manager.get_memory_by_key("list:shopping")
        assert shopping_list is not None
        assert shopping_list.content == "Shopping list: bananas."
    finally:
        gateway.close()


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
    assert context.memories == (
        MemoryReference(
            memory_id=1,
            content="User prefers tea.",
            layer="profile",
            revision=1,
        ),
    )


@pytest.mark.integration
def test_failed_embedding_is_reconciled_after_reopen(tmp_path) -> None:
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
        assert confirmation.memory_operation.succeeded is True
        assert confirmation.memory_operation.reason == "stored_pending_index"
        assert confirmation.errors == ()
        memories = manager.get_all_memories()
        assert len(memories) == 1
        assert memories[0].indexed_revision == 0
    finally:
        pipeline.close()

    reopened_manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    try:
        memories = reopened_manager.get_all_memories()
        assert len(memories) == 1
        assert memories[0].content == "User prefers tea."
        assert memories[0].indexed_revision == memories[0].revision == 1
        assert reopened_manager.vector_store.has_vector(memories[0].id)
    finally:
        reopened_manager.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    (
        "scope",
        "list_name",
        "memory_key",
        "initial_item",
        "additional_item",
        "expected",
    ),
    (
        (
            "list_relevant",
            "shopping",
            "list:shopping",
            "milk",
            "bread",
            "Shopping list: milk, bread.",
        ),
        (
            "task_relevant_only",
            "task",
            "list:tasks",
            "call the dentist",
            "buy stamps",
            "Task list: call the dentist, buy stamps.",
        ),
    ),
)
def test_first_structured_list_item_is_stored_then_later_items_are_updated(
    tmp_path,
    scope,
    list_name,
    memory_key,
    initial_item,
    additional_item,
    expected,
) -> None:
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memories.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
        embedding_dimension=4,
    )
    manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    gateway = MemoryManagerGateway(manager)

    first_action = MemoryAction(
        action="store",
        content=None,
        rationale="User added the first structured-list item.",
        target=MemoryTarget(memory_key=memory_key),
        list_operation=StructuredListOperation(
            list_name=list_name,
            operation="add_items",
            items=(initial_item,),
        ),
    )
    later_action = MemoryAction(
        action="update",
        content=None,
        rationale="User added another structured-list item.",
        target=MemoryTarget(memory_key=memory_key, expected_revision=1),
        list_operation=StructuredListOperation(
            list_name=list_name,
            operation="add_items",
            items=(additional_item,),
        ),
    )

    try:
        assert gateway.apply(first_action, scope).status is (
            MemoryOperationStatus.STORED_SUCCESSFULLY
        )
        assert gateway.apply(later_action, scope).status is (
            MemoryOperationStatus.UPDATED_SUCCESSFULLY
        )
        structured_list = manager.memory_store.get_memory_by_key(memory_key)
    finally:
        gateway.close()

    assert structured_list is not None
    assert structured_list.content == expected


@pytest.mark.integration
def test_gateway_blocks_exact_mutation_outside_active_scope(tmp_path) -> None:
    config = LocalMemoryConfig(
        memory_db_path=tmp_path / "memories.sqlite3",
        vector_db_path=tmp_path / "vectors.sqlite3",
        embedding_dimension=4,
    )
    manager = build_memory_manager(
        config,
        embedding_service=DeterministicEmbeddingService(),
        validator=FailingValidator(),
    )
    gateway = MemoryManagerGateway(manager)
    stored = manager.store_memory(
        content="User prefers tea.",
        layer="profile",
        validate=False,
        auto_classify=False,
        auto_extract=False,
    )
    assert stored.memory_id is not None
    action = MemoryAction(
        action="delete",
        content="User prefers tea.",
        rationale="Attempted cross-scope deletion.",
        target=MemoryTarget(memory_id=stored.memory_id, expected_revision=1),
    )

    try:
        outcome = gateway.apply(action, "list_relevant")
        memory = manager.memory_store.get_memory_by_id(stored.memory_id)
    finally:
        gateway.close()

    assert outcome.status is MemoryOperationStatus.MEMORY_SCOPE_MISMATCH
    assert memory is not None
    assert memory.content == "User prefers tea."
