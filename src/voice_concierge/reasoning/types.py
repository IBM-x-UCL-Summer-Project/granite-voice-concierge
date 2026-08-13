"""Shared request and response types for local reasoning.

The reasoning package sits between voice input, context/memory retrieval, and
voice output. These types define that boundary: callers provide a normalized
request with already transcribed speech and any available context, and the
reasoning engine returns a speakable response plus structured suggestions for
other components.

Reasoning does not own persistence, audio capture, text-to-speech, or mode
state. For example, it may propose a memory operation, but the memory component
is responsible for confirmation, storage, deletion, and retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Confidence = Literal["low", "medium", "high"]
MemoryActionKind = Literal["store", "delete", "update"]
StructuredListName = Literal["shopping", "task"]
StructuredListOperationKind = Literal["add_items"]
SHOPPING_LIST_MEMORY_KEY = "list:shopping"
TASK_LIST_MEMORY_KEY = "list:tasks"
STRUCTURED_LIST_MEMORY_KEYS = frozenset(
    {SHOPPING_LIST_MEMORY_KEY, TASK_LIST_MEMORY_KEY}
)
InformationSource = Literal[
    "none",
    "user_input",
    "local_context",
    "stable_knowledge",
    "runtime_live",
    "external_live",
]
InformationEvidenceSource = Literal["memory", "conversation_summary"]
FreshnessRequirement = Literal["not_required", "current"]


@dataclass(frozen=True)
class MemoryTarget:
    """Exact identity and optional revision expected for a memory mutation."""

    memory_id: int | None = None
    memory_key: str | None = None
    expected_revision: int | None = None

    def __post_init__(self) -> None:
        if self.memory_id is None and self.memory_key is None:
            raise ValueError("Memory target requires an ID or stable key.")
        if self.memory_id is not None and (
            not isinstance(self.memory_id, int)
            or isinstance(self.memory_id, bool)
            or self.memory_id <= 0
        ):
            raise ValueError("Memory target ID must be positive.")
        if self.memory_key is not None and (
            not isinstance(self.memory_key, str) or not self.memory_key.strip()
        ):
            raise ValueError("Memory target key must not be blank.")
        if self.expected_revision is not None and (
            not isinstance(self.expected_revision, int)
            or isinstance(self.expected_revision, bool)
            or self.expected_revision <= 0
        ):
            raise ValueError("Expected memory revision must be positive.")


@dataclass(frozen=True)
class MemoryReference:
    """Typed memory evidence supplied to reasoning without losing identity."""

    memory_id: int
    content: str
    layer: str
    revision: int
    memory_key: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.memory_id, int)
            or isinstance(self.memory_id, bool)
            or self.memory_id <= 0
        ):
            raise ValueError("Memory reference ID must be positive.")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision <= 0
        ):
            raise ValueError("Memory reference revision must be positive.")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Memory reference content must not be blank.")
        if not isinstance(self.layer, str) or not self.layer.strip():
            raise ValueError("Memory reference layer must not be blank.")
        if self.memory_key is not None and (
            not isinstance(self.memory_key, str) or not self.memory_key.strip()
        ):
            raise ValueError("Memory reference key must not be blank.")
        if self.topic is not None and not isinstance(self.topic, str):
            raise ValueError("Memory reference topic must be a string.")

    def mutation_target(self) -> MemoryTarget:
        """Return an exact, revision-checked target for this record."""

        return MemoryTarget(
            memory_id=self.memory_id,
            memory_key=self.memory_key,
            expected_revision=self.revision,
        )

    def information_evidence(self) -> InformationEvidence:
        """Return an exact evidence citation for this supplied record."""

        return InformationEvidence(
            source="memory",
            quote=self.content,
            memory_id=self.memory_id,
            memory_revision=self.revision,
        )


@dataclass(frozen=True)
class InformationEvidence:
    """Verifiable local-context evidence cited by a reasoning response."""

    source: InformationEvidenceSource
    quote: str
    memory_id: int | None = None
    memory_revision: int | None = None

    def __post_init__(self) -> None:
        if self.source not in {"memory", "conversation_summary"}:
            raise ValueError(f"Unsupported information evidence: {self.source!r}.")
        if not isinstance(self.quote, str) or not self.quote.strip():
            raise ValueError("Information evidence quote must not be blank.")
        if self.source == "memory":
            if (
                not isinstance(self.memory_id, int)
                or isinstance(self.memory_id, bool)
                or self.memory_id <= 0
            ):
                raise ValueError("Memory evidence ID must be positive.")
            if (
                not isinstance(self.memory_revision, int)
                or isinstance(self.memory_revision, bool)
                or self.memory_revision <= 0
            ):
                raise ValueError("Memory evidence revision must be positive.")
            return
        if self.memory_id is not None or self.memory_revision is not None:
            raise ValueError(
                "Conversation-summary evidence cannot carry memory identity."
            )


@dataclass(frozen=True)
class StructuredListOperation:
    """Typed domain operation for changing a project-owned structured list."""

    list_name: StructuredListName
    operation: StructuredListOperationKind
    items: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.list_name not in {"shopping", "task"}:
            raise ValueError(f"Unsupported structured list: {self.list_name!r}.")
        if self.operation != "add_items":
            raise ValueError(
                f"Unsupported structured-list operation: {self.operation!r}."
            )
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("Structured-list items must be a non-empty tuple.")

        normalized_items: list[str] = []
        seen: set[str] = set()
        for item in self.items:
            if not isinstance(item, str) or not item.strip(" ."):
                raise ValueError("Structured-list items must not be blank.")
            normalized = item.strip(" .")
            comparison_key = normalized.casefold()
            if comparison_key not in seen:
                normalized_items.append(normalized)
                seen.add(comparison_key)
        object.__setattr__(self, "items", tuple(normalized_items))

    @property
    def memory_key(self) -> str:
        """Return the stable memory key owned by this list."""

        if self.list_name == "shopping":
            return SHOPPING_LIST_MEMORY_KEY
        return TASK_LIST_MEMORY_KEY


@dataclass(frozen=True)
class ReasoningConstraints:
    """Runtime limits and policy flags applied to a reasoning request.

    These constraints let the caller adapt the same reasoning interface to
    different runtime conditions without changing the engine implementation.
    The current defaults reflect the project brief: local/offline execution,
    concise voice-first responses, and explicit handling for memory writes.
    """

    #: Whether the response must avoid cloud services or network only behavior.
    offline: bool = True
    #: Whether output should be optimized for spoken delivery instead of reading.
    voice_first: bool = True
    #: Soft upper bound for the spoken response produced by the engine.
    max_words: int = 60
    #: Whether the engine is allowed to propose memory writes in its response.
    allow_memory_writes: bool = True


@dataclass(frozen=True)
class ReasoningRequest:
    """Input contract for a single local reasoning turn.

    The request should contain information that has already been prepared by
    upstream components. Speech-to-text supplies ``transcript``; context or app
    state supplies ``mode``; memory retrieval supplies ``memories``; and any
    rolling dialogue state is passed as ``conversation_summary``. Keeping these
    responsibilities separate makes it possible to swap the reasoning backend
    without coupling it to voice, memory, or application plumbing.
    """

    #: User speech after transcription and basic normalization.
    transcript: str
    #: Current behavior profile or app mode chosen outside the reasoning engine.
    mode: str = "home"
    #: Relevant retrieved memories with stable identity and revision metadata.
    memories: tuple[MemoryReference, ...] = ()
    #: Optional compact summary of prior turns supplied by conversation state.
    conversation_summary: str | None = None
    #: Runtime policy and output-shaping constraints for this request.
    constraints: ReasoningConstraints = field(default_factory=ReasoningConstraints)


@dataclass(frozen=True)
class MemoryAction:
    """A proposed memory operation for the memory component to evaluate.

    This is intentionally a proposal rather than a command. The reasoning layer
    can identify that something appears worth storing, updating, or deleting,
    but the memory layer owns confirmation rules, persistence, conflict
    handling, and auditability.
    """

    #: Requested operation type.
    action: MemoryActionKind
    #: Memory content or delete-target description; absent for typed list changes.
    content: str | None
    #: Short explanation of why this operation was proposed.
    rationale: str
    #: Exact ID/key and optional expected revision for the affected record.
    target: MemoryTarget | None = None
    #: Typed structured-list mutation, used instead of encoding commands in content.
    list_operation: StructuredListOperation | None = None
    #: Whether another component should confirm with the user before execution.
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.action not in {"store", "update", "delete"}:
            raise ValueError(f"Unsupported memory action: {self.action!r}.")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("Memory action rationale must not be blank.")
        if self.target is not None and not isinstance(self.target, MemoryTarget):
            raise ValueError("Memory action target must be a MemoryTarget.")
        if not isinstance(self.requires_confirmation, bool):
            raise ValueError("Memory action confirmation flag must be boolean.")
        if self.list_operation is not None and not isinstance(
            self.list_operation,
            StructuredListOperation,
        ):
            raise ValueError(
                "Memory action list operation must be a StructuredListOperation."
            )
        if self.action in {"update", "delete"} and self.target is None:
            raise ValueError(f"Memory {self.action} requires an exact target.")
        if (
            self.action == "store"
            and self.target is not None
            and self.target.memory_id is not None
        ):
            raise ValueError("A memory store cannot target an existing memory ID.")
        if self.list_operation is None:
            if not isinstance(self.content, str) or not self.content.strip():
                raise ValueError("Memory action content must not be blank.")
            if (
                self.action in {"store", "update"}
                and self.target is not None
                and self.target.memory_key in STRUCTURED_LIST_MEMORY_KEYS
            ):
                raise ValueError(
                    "Structured-list writes require a typed list operation."
                )
            return

        if self.action not in {"store", "update"}:
            raise ValueError("Structured-list operations support store or update only.")
        if self.content is not None:
            raise ValueError(
                "Structured-list operations must not duplicate items in content."
            )
        if self.target is None:
            raise ValueError("Structured-list operations require an exact target.")
        if self.target.memory_key not in {None, self.list_operation.memory_key}:
            raise ValueError("Structured-list operation does not match target key.")


@dataclass(frozen=True)
class ReasoningResponse:
    """Output contract returned by a reasoning engine.

    ``spoken_response`` is the only field that should go directly to
    text-to-speech. The remaining fields are structured signals for the app
    pipeline: whether to ask for confirmation, whether to hand off a proposed
    memory change, whether a different mode may fit better, and how confident
    the engine is in the result.
    """

    #: TTS-ready answer intended to be spoken to the user.
    spoken_response: str
    #: Whether the assistant should ask before taking a follow-up action.
    needs_confirmation: bool = False
    #: Optional memory operation proposal; execution belongs to memory code.
    proposed_memory_action: MemoryAction | None = None
    #: Optional hint that context/mode management may want to switch modes.
    mode_suggestion: str | None = None
    #: Coarse confidence level for routing, logging, or fallback decisions.
    confidence: Confidence = "medium"
    #: Source required to fulfil this request, declared by the reasoning backend.
    required_information_source: InformationSource = "none"
    #: Exact supplied local evidence used when the declared source is local context.
    information_evidence: tuple[InformationEvidence, ...] = ()
    #: Whether correctness depends on the information being current.
    freshness_requirement: FreshnessRequirement = "not_required"
    #: Backend-specific diagnostics that should not affect core behavior.
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningTrace:
    """Raw model output and final response produced from one generation."""

    #: Parsed model response before deterministic policy and output shaping.
    raw_response: ReasoningResponse
    #: User-visible response after policy guards and output shaping.
    guarded_response: ReasoningResponse
