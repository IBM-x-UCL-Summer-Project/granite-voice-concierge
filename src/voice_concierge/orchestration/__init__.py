"""Compatibility API over the canonical ``voice_concierge.app`` pipeline."""

from voice_concierge.orchestration.adapters import (
    MemoryManagerGateway,
    OfflineTTSSpeechGateway,
)
from voice_concierge.orchestration.orchestrator import ConciergeOrchestrator
from voice_concierge.orchestration.types import (
    MemoryGateway,
    MemoryOperationResult,
    SpeechGateway,
    TurnError,
    TurnResult,
)

__all__ = [
    "ConciergeOrchestrator",
    "MemoryGateway",
    "MemoryManagerGateway",
    "MemoryOperationResult",
    "OfflineTTSSpeechGateway",
    "SpeechGateway",
    "TurnError",
    "TurnResult",
]
