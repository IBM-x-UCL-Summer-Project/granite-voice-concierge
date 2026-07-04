"""Public interfaces and implementations for local reasoning."""

from voice_concierge.reasoning.engine import (
    DeterministicReasoningFake,
    ReasoningEngine,
    TraceableReasoningEngine,
)
from voice_concierge.reasoning.errors import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningError,
    ReasoningModelUnavailableError,
    ReasoningRequestError,
)
from voice_concierge.reasoning.factory import build_reasoning_engine
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
from voice_concierge.reasoning.validation import validate_reasoning_request

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
    "ReasoningBackendUnavailableError",
    "ReasoningConstraints",
    "ReasoningConfigurationError",
    "ReasoningEngine",
    "ReasoningError",
    "ReasoningModelUnavailableError",
    "ReasoningModelSelection",
    "ReasoningRequest",
    "ReasoningRequestError",
    "ReasoningResponse",
    "ReasoningTrace",
    "TraceableReasoningEngine",
    "apply_spoken_word_limit",
    "build_granite_messages",
    "build_reasoning_engine",
    "default_model_selection",
    "load_model_selection",
    "load_prompt_template",
    "save_model_selection",
    "validate_reasoning_request",
]
