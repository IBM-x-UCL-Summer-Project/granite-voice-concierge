# src/voice_concierge/routines/__init__.py
"""Voice-free routine core and the thin voice adapter for guided routines."""

from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.factory import build_routine_adapter
from voice_concierge.routines.fakes import StaticRoutineProvider
from voice_concierge.routines.intent import ROUTINE_TRIGGERS, is_routine_request
from voice_concierge.routines.interfaces import (
    CommandWaiter,
    RoutineProvider,
    StepSpeaker,
)
from voice_concierge.routines.providers import (
    ChainedRoutineProvider,
    LLMRoutineProvider,
    MemoryRoutineProvider,
    deserialize_routine,
    parse_numbered_steps,
    serialize_routine,
)
from voice_concierge.routines.runner import RoutineRunner
from voice_concierge.routines.session import RoutineSession
from voice_concierge.routines.types import (
    Routine,
    RoutineResponse,
    RoutineStep,
    StepView,
)

__all__ = [
    "ROUTINE_TRIGGERS",
    "ChainedRoutineProvider",
    "CommandWaiter",
    "LLMRoutineProvider",
    "MemoryRoutineProvider",
    "Routine",
    "RoutineCommandAdapter",
    "RoutineError",
    "RoutineProvider",
    "RoutineResponse",
    "RoutineRunner",
    "RoutineSession",
    "RoutineStep",
    "StaticRoutineProvider",
    "StepSpeaker",
    "StepView",
    "build_routine_adapter",
    "deserialize_routine",
    "is_routine_request",
    "parse_numbered_steps",
    "serialize_routine",
]
