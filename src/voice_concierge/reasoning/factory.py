"""Application-facing construction helpers for local reasoning runtimes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

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
    ReasoningModelSelection,
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

    primary_config = OllamaConfig(
        model=selection.model,
        host=selection.host or DEFAULT_OLLAMA_HOST,
        timeout_s=timeout_s,
        prompt_version=prompt_version,
    )

    manager = model_manager or OllamaModelManager(
        OllamaModelManagerConfig(
            host=primary_config.host,
            timeout_s=timeout_s,
        )
    )
    runtime_model, model_role = _select_runtime_model(
        selection,
        manager,
        host=primary_config.host,
    )
    config = replace(
        primary_config,
        model=runtime_model,
        model_role=model_role,
    )

    return OllamaReasoningEngine(config)


def _select_runtime_model(
    selection: ReasoningModelSelection,
    manager: ModelManager,
    *,
    host: str,
) -> tuple[str, Literal["primary", "fallback"]]:
    """Select an already-installed startup model under the persisted policy."""

    if _model_is_available(selection.model, manager, host=host):
        return selection.model, "primary"

    if selection.fallback_policy == "disabled":
        raise ReasoningModelUnavailableError(
            f"Selected reasoning model is not available locally: "
            f"{selection.model!r}. Fallback is disabled."
        )

    fallback_model = selection.fallback_model
    assert fallback_model is not None
    if _model_is_available(fallback_model, manager, host=host):
        return fallback_model, "fallback"

    raise ReasoningModelUnavailableError(
        "Neither the selected reasoning model nor its configured fallback is "
        f"available locally: {selection.model!r}, {fallback_model!r}."
    )


def _model_is_available(model: str, manager: ModelManager, *, host: str) -> bool:
    """Check one installed model and preserve backend-vs-model failure semantics."""

    try:
        manager.show_model(model)
    except OllamaModelManagementError as exc:
        if _missing_selected_model(exc):
            return False

        raise ReasoningBackendUnavailableError(
            f"Could not verify local reasoning model {model!r} at {host}: {exc}"
        ) from exc
    return True


def _missing_selected_model(exc: OllamaModelManagementError) -> bool:
    cause = exc.__cause__
    return isinstance(cause, ResponseError) and cause.status_code == 404
