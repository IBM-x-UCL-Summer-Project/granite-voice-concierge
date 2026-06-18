"""Local reasoning interfaces and prototype implementations."""

from voice_concierge.reasoning.engine import (
    ReasoningEngine,
    RuleBasedReasoningPrototype,
    TraceableReasoningEngine,
)
from voice_concierge.reasoning.models import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL_BACKEND,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_REASONING_MODEL,
    LocalModelDetails,
    LocalModelInfo,
    ModelDownloadProgress,
    ModelManager,
    ReasoningModelSelection,
    default_model_selection,
    load_model_selection,
    save_model_selection,
)
from voice_concierge.reasoning.ollama import (
    OllamaConfig,
    OllamaModelManagementError,
    OllamaModelManager,
    OllamaModelManagerConfig,
    OllamaReasoningEngine,
    OllamaReasoningError,
)
from voice_concierge.reasoning.prompting import ChatMessage, build_granite_messages
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)

__all__ = [
    "MemoryAction",
    "ReasoningConstraints",
    "ReasoningEngine",
    "ReasoningRequest",
    "ReasoningResponse",
    "ReasoningTrace",
    "RuleBasedReasoningPrototype",
    "TraceableReasoningEngine",
    "ChatMessage",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_MODEL_BACKEND",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_REASONING_MODEL",
    "LocalModelDetails",
    "LocalModelInfo",
    "ModelDownloadProgress",
    "ModelManager",
    "OllamaConfig",
    "OllamaModelManagementError",
    "OllamaModelManager",
    "OllamaModelManagerConfig",
    "OllamaReasoningEngine",
    "OllamaReasoningError",
    "ReasoningModelSelection",
    "build_granite_messages",
    "default_model_selection",
    "load_model_selection",
    "save_model_selection",
]
