"""Application-facing construction helpers for local reasoning runtimes."""

from __future__ import annotations

from pathlib import Path

from ollama import ResponseError

from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.reasoning.errors import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelUnavailableError,
)
from voice_concierge.reasoning.models import (
    DEFAULT_MODEL_SELECTION_PATH,
    DEFAULT_OLLAMA_HOST,
    ModelManager,
    load_model_selection,
)
from voice_concierge.reasoning.ollama import (
    OllamaConfig,
    OllamaModelManagementError,
    OllamaModelManager,
    OllamaModelManagerConfig,
    OllamaReasoningEngine,
)
from voice_concierge.reasoning.prompting import (
    DEFAULT_PROMPT_VERSION,
    PromptTemplateError,
    load_prompt_template,
)


def build_reasoning_engine(
    selection_path: str | Path = DEFAULT_MODEL_SELECTION_PATH,
    *,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    timeout_s: float = 120.0,
    model_manager: ModelManager | None = None,
) -> ReasoningEngine:
    """Build the selected local reasoning engine for application code."""

    try:
        selection = load_model_selection(Path(selection_path))
    except (OSError, ValueError) as exc:
        raise ReasoningConfigurationError(
            f"Invalid reasoning model selection: {exc}"
        ) from exc

    if selection.backend != "ollama":
        raise ReasoningConfigurationError(
            f"Unsupported reasoning model backend: {selection.backend!r}."
        )

    try:
        load_prompt_template(prompt_version)
    except PromptTemplateError as exc:
        raise ReasoningConfigurationError(
            f"Invalid reasoning prompt version: {prompt_version!r}."
        ) from exc

    config = OllamaConfig(
        model=selection.model,
        host=selection.host or DEFAULT_OLLAMA_HOST,
        timeout_s=timeout_s,
        prompt_version=prompt_version,
    )

    manager = model_manager or OllamaModelManager(
        OllamaModelManagerConfig(
            host=config.host,
            timeout_s=timeout_s,
        )
    )
    try:
        manager.show_model(selection.model)
    except OllamaModelManagementError as exc:
        if _missing_selected_model(exc):
            raise ReasoningModelUnavailableError(
                f"Selected reasoning model is not available locally: "
                f"{selection.model!r}."
            ) from exc

        raise ReasoningBackendUnavailableError(
            f"Could not verify local reasoning backend at {config.host}: {exc}"
        ) from exc

    return OllamaReasoningEngine(config)


def _missing_selected_model(exc: OllamaModelManagementError) -> bool:
    cause = exc.__cause__
    return isinstance(cause, ResponseError) and cause.status_code == 404
