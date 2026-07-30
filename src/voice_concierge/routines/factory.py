# src/voice_concierge/routines/factory.py
"""Construction helpers for the routines stack."""

# Local
from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.providers import (
    ChainedRoutineProvider,
    LLMRoutineProvider,
    MemoryRoutineProvider,
)


def build_routine_adapter(
    *,
    memory_manager: object,
    reasoning_engine: ReasoningEngine,
) -> RoutineCommandAdapter:
    """Wire a memory-first, LLM-fallback provider into a command adapter."""
    provider = ChainedRoutineProvider(
        [
            MemoryRoutineProvider(memory_manager),
            LLMRoutineProvider(reasoning_engine),
        ]
    )
    return RoutineCommandAdapter(provider)
