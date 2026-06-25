"""Public interfaces and implementations for local reasoning."""

from voice_concierge.reasoning.engine import (
    DeterministicReasoningFake,
    ReasoningEngine,
    TraceableReasoningEngine,
)
from voice_concierge.reasoning.models import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL_BACKEND,
    DEFAULT_MODEL_SELECTION_PATH,
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
from voice_concierge.reasoning.output import apply_spoken_word_limit
from voice_concierge.reasoning.prompting import (
    DEFAULT_PROMPT_VERSION,
    ChatMessage,
    PromptTemplate,
    PromptTemplateError,
    build_granite_messages,
    load_prompt_template,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)

__all__ = [
    "ChatMessage",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_MODEL_BACKEND",
    "DEFAULT_MODEL_SELECTION_PATH",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_REASONING_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DeterministicReasoningFake",
    "LocalModelDetails",
    "LocalModelInfo",
    "MemoryAction",
    "ModelDownloadProgress",
    "ModelManager",
    "OllamaConfig",
    "OllamaModelManagementError",
    "OllamaModelManager",
    "OllamaModelManagerConfig",
    "OllamaReasoningEngine",
    "OllamaReasoningError",
    "PromptTemplate",
    "PromptTemplateError",
    "ReasoningConstraints",
    "ReasoningEngine",
    "ReasoningModelSelection",
    "ReasoningRequest",
    "ReasoningResponse",
    "ReasoningTrace",
    "TraceableReasoningEngine",
    "apply_spoken_word_limit",
    "build_granite_messages",
    "default_model_selection",
    "load_model_selection",
    "load_prompt_template",
    "save_model_selection",
]
