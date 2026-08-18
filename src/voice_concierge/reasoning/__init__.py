"""Public interfaces and implementations for local reasoning.

The Ollama-backed implementation is loaded lazily so callers that only use the
backend-neutral contracts or deterministic test pipeline do not need the
optional runtime client at import time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from voice_concierge.reasoning.engine import (
    DeterministicReasoningFake,
    ReasoningEngine,
    TraceableReasoningEngine,
)
from voice_concierge.reasoning.errors import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningError,
    ReasoningGenerationError,
    ReasoningModelUnavailableError,
    ReasoningRequestError,
    ReasoningTimeoutError,
)
from voice_concierge.reasoning.models import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL_BACKEND,
    DEFAULT_MODEL_FALLBACK_POLICY,
    DEFAULT_MODEL_SELECTION_PATH,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_REASONING_MODEL,
    LocalModelDetails,
    LocalModelInfo,
    ModelDownloadProgress,
    ModelFallbackPolicy,
    ModelManager,
    ReasoningModelSelection,
    default_model_selection,
    load_model_selection,
    save_model_selection,
)
from voice_concierge.reasoning.output import apply_spoken_word_limit
from voice_concierge.reasoning.profiles import (
    STRICT_REASONING_POLICY_PROFILE,
    SUPPORTED_REASONING_POLICY_PROFILES,
    UAT_REASONING_POLICY_PROFILE,
    ReasoningPolicyProfile,
    validate_reasoning_policy_profile,
)
from voice_concierge.reasoning.prompting import (
    DEFAULT_PROMPT_VERSION,
    ChatMessage,
    PromptTemplate,
    PromptTemplateError,
    build_granite_messages,
    load_prompt_template,
)
from voice_concierge.reasoning.types import (
    SHOPPING_LIST_MEMORY_KEY,
    STRUCTURED_LIST_MEMORY_KEYS,
    TASK_LIST_MEMORY_KEY,
    FreshnessRequirement,
    InformationEvidence,
    InformationEvidenceSource,
    InformationSource,
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
    RuntimeReference,
    StructuredListOperation,
)
from voice_concierge.reasoning.validation import validate_reasoning_request

__all__ = [
    "ChatMessage",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_MODEL_BACKEND",
    "DEFAULT_MODEL_FALLBACK_POLICY",
    "DEFAULT_MODEL_SELECTION_PATH",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_REASONING_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DeterministicReasoningFake",
    "LocalModelDetails",
    "LocalModelInfo",
    "FreshnessRequirement",
    "InformationEvidence",
    "InformationEvidenceSource",
    "InformationSource",
    "MemoryAction",
    "MemoryReference",
    "MemoryTarget",
    "ModelDownloadProgress",
    "ModelFallbackPolicy",
    "ModelManager",
    "OllamaBackendUnavailableError",
    "OllamaConfig",
    "OllamaGenerationError",
    "OllamaModelUnavailableError",
    "OllamaModelManagementError",
    "OllamaModelManager",
    "OllamaModelManagerConfig",
    "OllamaReasoningEngine",
    "OllamaReasoningError",
    "OllamaTimeoutError",
    "PromptTemplate",
    "PromptTemplateError",
    "ReasoningBackendUnavailableError",
    "ReasoningConstraints",
    "ReasoningConfigurationError",
    "ReasoningEngine",
    "ReasoningError",
    "ReasoningGenerationError",
    "ReasoningModelUnavailableError",
    "ReasoningModelSelection",
    "ReasoningPolicyProfile",
    "ReasoningRequest",
    "ReasoningRequestError",
    "ReasoningResponse",
    "ReasoningTrace",
    "ReasoningTimeoutError",
    "RuntimeReference",
    "STRICT_REASONING_POLICY_PROFILE",
    "SHOPPING_LIST_MEMORY_KEY",
    "STRUCTURED_LIST_MEMORY_KEYS",
    "StructuredListOperation",
    "SUPPORTED_REASONING_POLICY_PROFILES",
    "TASK_LIST_MEMORY_KEY",
    "TraceableReasoningEngine",
    "UAT_REASONING_POLICY_PROFILE",
    "apply_spoken_word_limit",
    "build_granite_messages",
    "build_reasoning_engine",
    "default_model_selection",
    "load_model_selection",
    "load_prompt_template",
    "save_model_selection",
    "validate_reasoning_request",
    "validate_reasoning_policy_profile",
]


def __getattr__(name: str) -> Any:
    if name == "build_reasoning_engine":
        module_name = "voice_concierge.reasoning.factory"
    elif name.startswith("Ollama"):
        module_name = "voice_concierge.reasoning.ollama"
    else:
        raise AttributeError(name)

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
