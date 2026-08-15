"""Local reasoning model metadata and selection helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from voice_concierge.local_storage import REASONING_MODEL_SELECTION_PATH

DEFAULT_MODEL_BACKEND = "ollama"
DEFAULT_REASONING_MODEL = "granite4.1:8b"
DEFAULT_FALLBACK_MODEL = "granite3.3:2b"
DEFAULT_MODEL_FALLBACK_POLICY = "startup_missing_primary"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL_SELECTION_PATH = REASONING_MODEL_SELECTION_PATH
MODEL_SELECTION_SCHEMA_VERSION = 2
_LEGACY_MODEL_SELECTION_SCHEMA_VERSION = 1

ModelFallbackPolicy = Literal["disabled", "startup_missing_primary"]


@dataclass(frozen=True)
class LocalModelInfo:
    """Summary of a locally installed model."""

    name: str
    model: str
    modified_at: str | None = None
    size_bytes: int | None = None
    digest: str | None = None
    format: str | None = None
    family: str | None = None
    families: tuple[str, ...] = ()
    parameter_size: str | None = None
    quantization_level: str | None = None


@dataclass(frozen=True)
class LocalModelDetails:
    """Detailed metadata for a local model."""

    model: str
    modified_at: str | None = None
    format: str | None = None
    family: str | None = None
    families: tuple[str, ...] = ()
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: tuple[str, ...] = ()
    parameters: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class ModelDownloadProgress:
    """Progress update from a local model download operation."""

    status: str
    digest: str | None = None
    total: int | None = None
    completed: int | None = None


@dataclass(frozen=True)
class ReasoningModelSelection:
    """Persisted active-model choice for local reasoning."""

    backend: str = DEFAULT_MODEL_BACKEND
    model: str = DEFAULT_REASONING_MODEL
    fallback_model: str | None = DEFAULT_FALLBACK_MODEL
    host: str = DEFAULT_OLLAMA_HOST
    fallback_policy: ModelFallbackPolicy = DEFAULT_MODEL_FALLBACK_POLICY

    def __post_init__(self) -> None:
        for field_name in ("backend", "model", "host"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Model selection {field_name} must be a non-empty string."
                )
            object.__setattr__(self, field_name, value.strip())

        if self.fallback_model is not None:
            if not isinstance(self.fallback_model, str) or not (
                normalized_fallback := self.fallback_model.strip()
            ):
                raise ValueError(
                    "Model selection fallback_model must be a non-empty string "
                    "or null."
                )
            object.__setattr__(self, "fallback_model", normalized_fallback)

        if self.fallback_policy not in ("disabled", "startup_missing_primary"):
            raise ValueError(
                "Model selection fallback_policy must be 'disabled' or "
                "'startup_missing_primary'."
            )
        if self.fallback_policy == "startup_missing_primary":
            if self.fallback_model is None:
                raise ValueError("startup_missing_primary requires a fallback_model.")
            if self.fallback_model == self.model:
                raise ValueError(
                    "Model selection fallback_model must differ from model."
                )


class ModelManager(Protocol):
    """Backend-neutral interface for local model management."""

    def list_models(self) -> tuple[LocalModelInfo, ...]:
        """Return locally installed models."""

    def show_model(self, model: str) -> LocalModelDetails:
        """Return detailed metadata for a local model."""

    def pull_model(
        self,
        model: str,
        *,
        stream: bool = False,
    ) -> tuple[ModelDownloadProgress, ...]:
        """Download a model and return progress updates."""


def default_model_selection() -> ReasoningModelSelection:
    """Return the current default local reasoning model selection."""

    return ReasoningModelSelection()


def load_model_selection(path: Path) -> ReasoningModelSelection:
    """Load a model selection from disk, or return defaults if missing."""

    if not path.exists():
        return default_model_selection()

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Model selection config must be a JSON object.")

    version = data.get("schema_version", _LEGACY_MODEL_SELECTION_SCHEMA_VERSION)
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version
        not in (
            _LEGACY_MODEL_SELECTION_SCHEMA_VERSION,
            MODEL_SELECTION_SCHEMA_VERSION,
        )
    ):
        raise ValueError(f"Unsupported model selection schema version: {version!r}")

    fallback_policy: object = data.get(
        "fallback_policy",
        (
            "disabled"
            if version == _LEGACY_MODEL_SELECTION_SCHEMA_VERSION
            else DEFAULT_MODEL_FALLBACK_POLICY
        ),
    )

    return ReasoningModelSelection(
        backend=_non_empty_string(data.get("backend"), DEFAULT_MODEL_BACKEND),
        model=_non_empty_string(data.get("model"), DEFAULT_REASONING_MODEL),
        fallback_model=_optional_non_empty_string(
            data.get("fallback_model", DEFAULT_FALLBACK_MODEL),
            "fallback_model",
        ),
        fallback_policy=_fallback_policy(fallback_policy),
        host=_non_empty_string(data.get("host"), DEFAULT_OLLAMA_HOST),
    )


def save_model_selection(selection: ReasoningModelSelection, path: Path) -> None:
    """Persist a model selection to disk as local JSON config."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": MODEL_SELECTION_SCHEMA_VERSION,
        **asdict(selection),
    }
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _non_empty_string(value: object, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Model selection fields must be non-empty strings.")
    return value.strip()


def _optional_non_empty_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Model selection {field_name} must be a non-empty string or null."
        )
    return value.strip()


def _fallback_policy(value: object) -> ModelFallbackPolicy:
    if value not in ("disabled", "startup_missing_primary"):
        raise ValueError(
            "Model selection fallback_policy must be 'disabled' or "
            "'startup_missing_primary'."
        )
    return cast(ModelFallbackPolicy, value)
