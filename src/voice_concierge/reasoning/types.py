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
    #: Relevant retrieved memory snippets; this component does not fetch them.
    memories: tuple[str, ...] = ()
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
    #: User-facing memory content or target description.
    content: str
    #: Short explanation of why this operation was proposed.
    rationale: str
    #: Stable project-owned key for an exact structured-memory target.
    target_key: str | None = None
    #: Whether another component should confirm with the user before execution.
    requires_confirmation: bool = True


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
    #: Backend-specific diagnostics that should not affect core behavior.
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningTrace:
    """Raw model output and final response produced from one generation."""

    #: Parsed model response before deterministic policy and output shaping.
    raw_response: ReasoningResponse
    #: User-visible response after policy guards and output shaping.
    guarded_response: ReasoningResponse
