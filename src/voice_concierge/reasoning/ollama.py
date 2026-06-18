"""Ollama-backed local reasoning engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from voice_concierge.reasoning.models import (
    LocalModelDetails,
    LocalModelInfo,
    ModelDownloadProgress,
)
from voice_concierge.reasoning.policy import apply_reasoning_policy_guards
from voice_concierge.reasoning.prompting import build_granite_messages
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)


class OllamaReasoningError(RuntimeError):
    """Raised when the local Ollama runner cannot produce a usable response."""


class OllamaModelManagementError(RuntimeError):
    """Raised when local Ollama model management fails."""


REASONING_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "spoken_response": {
            "type": "string",
            "description": "Short response intended to be spoken aloud.",
        },
        "needs_confirmation": {
            "type": "boolean",
            "description": "True if the user must confirm before action is taken.",
        },
        "proposed_memory_action": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["store", "update", "delete"],
                        },
                        "content": {"type": "string"},
                        "rationale": {"type": "string"},
                        "requires_confirmation": {"type": "boolean"},
                    },
                    "required": [
                        "action",
                        "content",
                        "rationale",
                        "requires_confirmation",
                    ],
                },
                {"type": "null"},
            ]
        },
        "mode_suggestion": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
    },
    "required": [
        "spoken_response",
        "needs_confirmation",
        "proposed_memory_action",
        "mode_suggestion",
        "confidence",
    ],
}


@dataclass(frozen=True)
class OllamaConfig:
    """Configuration for the local Ollama reasoning backend."""

    model: str
    host: str = "http://localhost:11434"
    timeout_s: float = 120.0
    temperature: float = 0.2
    top_p: float = 0.9


class OllamaReasoningEngine:
    """Reasoning engine that calls a local Ollama chat endpoint."""

    def __init__(self, config: OllamaConfig) -> None:
        self.config = config

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        return self.generate_trace(request).guarded_response

    def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
        """Return parsed and policy-guarded responses from one Ollama request."""

        messages = [message.as_dict() for message in build_granite_messages(request)]
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "format": REASONING_RESPONSE_SCHEMA,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
            },
        }

        data = self._post_json("/api/chat", payload)
        content = self._extract_content(data)
        metadata = {
            "backend": "ollama",
            "model": self.config.model,
            "output_format": "structured_json",
            **self._extract_metrics(data),
        }
        raw_response = self._parse_response_content(content, metadata)
        guarded_response = apply_reasoning_policy_guards(request, raw_response)
        guarded_response = _with_word_limit(
            guarded_response,
            request.constraints.max_words,
        )
        return ReasoningTrace(
            raw_response=raw_response,
            guarded_response=guarded_response,
        )

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = f"{self.config.host.rstrip('/')}{path}"
        request = UrlRequest(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_s) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaReasoningError(
                f"Ollama request failed with HTTP {exc.code}: {body}"
            ) from exc
        except URLError as exc:
            raise OllamaReasoningError(
                f"Could not reach local Ollama runner at {url}: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise OllamaReasoningError("Ollama returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise OllamaReasoningError("Ollama response must be a JSON object.")

        return data

    def _extract_content(self, data: dict[str, object]) -> str:
        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaReasoningError("Ollama response did not include a message.")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaReasoningError("Ollama response message was empty.")

        return content.strip()

    def _parse_response_content(
        self,
        content: str,
        metadata: dict[str, str],
    ) -> ReasoningResponse:
        try:
            payload = json.loads(_strip_json_fence(content))
        except json.JSONDecodeError:
            return ReasoningResponse(
                spoken_response=content,
                confidence="low",
                metadata={
                    **metadata,
                    "structured_parse_error": "invalid_json",
                },
            )

        if not isinstance(payload, dict):
            return ReasoningResponse(
                spoken_response="I could not produce a structured response.",
                confidence="low",
                metadata={
                    **metadata,
                    "structured_parse_error": "not_object",
                },
            )

        try:
            return _response_from_payload(payload, metadata)
        except ValueError as exc:
            return ReasoningResponse(
                spoken_response="I could not produce a valid structured response.",
                confidence="low",
                metadata={
                    **metadata,
                    "structured_parse_error": str(exc),
                },
            )

    def _extract_metrics(self, data: dict[str, object]) -> dict[str, str]:
        metric_keys = (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "prompt_eval_duration",
            "eval_count",
            "eval_duration",
        )
        return {
            key: str(value)
            for key in metric_keys
            if isinstance((value := data.get(key)), int | float | str)
        }


@dataclass(frozen=True)
class OllamaModelManagerConfig:
    """Configuration for Ollama model management."""

    host: str = "http://localhost:11434"
    timeout_s: float = 180.0


class OllamaModelManager:
    """Model-management client for a local Ollama runner."""

    def __init__(self, config: OllamaModelManagerConfig | None = None) -> None:
        self.config = config or OllamaModelManagerConfig()

    def list_models(self) -> tuple[LocalModelInfo, ...]:
        data = self._get_json("/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise OllamaModelManagementError("Ollama model list must be an array.")

        return tuple(_model_info_from_payload(model) for model in models)

    def show_model(self, model: str) -> LocalModelDetails:
        model_name = _validated_model_name(model)
        data = self._post_json("/api/show", {"model": model_name})
        return _model_details_from_payload(model_name, data)

    def pull_model(
        self,
        model: str,
        *,
        stream: bool = False,
    ) -> tuple[ModelDownloadProgress, ...]:
        model_name = _validated_model_name(model)
        payload = {"model": model_name, "stream": stream}
        if not stream:
            data = self._post_json("/api/pull", payload)
            return (_download_progress_from_payload(data),)

        return tuple(self._stream_post_json("/api/pull", payload))

    def _get_json(self, path: str) -> dict[str, object]:
        url = f"{self.config.host.rstrip('/')}{path}"
        request = UrlRequest(url, method="GET")
        return _read_json_response(
            request,
            timeout_s=self.config.timeout_s,
            url=url,
            error_cls=OllamaModelManagementError,
        )

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = f"{self.config.host.rstrip('/')}{path}"
        request = UrlRequest(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return _read_json_response(
            request,
            timeout_s=self.config.timeout_s,
            url=url,
            error_cls=OllamaModelManagementError,
        )

    def _stream_post_json(
        self,
        path: str,
        payload: dict[str, object],
    ) -> tuple[ModelDownloadProgress, ...]:
        url = f"{self.config.host.rstrip('/')}{path}"
        request = UrlRequest(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_s) as response:
                updates = [
                    _download_progress_from_payload(_loads_json_line(line))
                    for line in response
                    if line.strip()
                ]
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaModelManagementError(
                f"Ollama request failed with HTTP {exc.code}: {body}"
            ) from exc
        except URLError as exc:
            raise OllamaModelManagementError(
                f"Could not reach local Ollama runner at {url}: {exc.reason}"
            ) from exc

        return tuple(updates)


def _read_json_response(
    request: UrlRequest,
    *,
    timeout_s: float,
    url: str,
    error_cls: type[RuntimeError],
) -> dict[str, object]:
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise error_cls(f"Ollama request failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise error_cls(
            f"Could not reach local Ollama runner at {url}: {exc.reason}"
        ) from exc

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise error_cls("Ollama returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise error_cls("Ollama response must be a JSON object.")

    return data


def _loads_json_line(line: bytes) -> dict[str, object]:
    try:
        data = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise OllamaModelManagementError("Ollama returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise OllamaModelManagementError("Ollama response must be a JSON object.")

    return data


def _response_from_payload(
    payload: dict[str, Any],
    metadata: dict[str, str],
) -> ReasoningResponse:
    spoken_response = _required_string(payload, "spoken_response")
    needs_confirmation = _required_bool(payload, "needs_confirmation")
    confidence = _confidence(payload.get("confidence"))
    proposed_memory_action = _memory_action(payload.get("proposed_memory_action"))
    mode_suggestion = _nullable_string(payload.get("mode_suggestion"))

    if proposed_memory_action and proposed_memory_action.requires_confirmation:
        needs_confirmation = True

    return ReasoningResponse(
        spoken_response=spoken_response,
        needs_confirmation=needs_confirmation,
        proposed_memory_action=proposed_memory_action,
        mode_suggestion=mode_suggestion,
        confidence=confidence,
        metadata=metadata,
    )


def _memory_action(value: object) -> MemoryAction | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise ValueError("memory_action_not_object")

    action = _required_string(value, "action")
    if action not in {"store", "update", "delete"}:
        raise ValueError("memory_action_invalid_action")

    return MemoryAction(
        action=action,
        content=_required_string(value, "content"),
        rationale=_required_string(value, "rationale"),
        requires_confirmation=_required_bool(value, "requires_confirmation"),
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}_missing_or_empty")
    return value.strip()


def _required_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key}_missing_or_not_bool")
    return value


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError("mode_suggestion_not_string_or_null")


def _confidence(value: object) -> str:
    if value in {"low", "medium", "high"}:
        return str(value)
    raise ValueError("confidence_invalid")


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _with_word_limit(
    response: ReasoningResponse,
    max_words: int,
) -> ReasoningResponse:
    limit = max(1, max_words)
    words = response.spoken_response.split()
    if len(words) <= limit:
        return response

    if response.needs_confirmation and response.proposed_memory_action:
        return ReasoningResponse(
            spoken_response=_confirmation_truncation_text(limit),
            needs_confirmation=response.needs_confirmation,
            proposed_memory_action=response.proposed_memory_action,
            mode_suggestion=response.mode_suggestion,
            confidence=response.confidence,
            metadata={**response.metadata, "truncated": "true"},
        )

    shortened = " ".join(words[:limit]).rstrip(".,;:")
    return ReasoningResponse(
        spoken_response=f"{shortened}.",
        needs_confirmation=response.needs_confirmation,
        proposed_memory_action=response.proposed_memory_action,
        mode_suggestion=response.mode_suggestion,
        confidence=response.confidence,
        metadata={**response.metadata, "truncated": "true"},
    )


def _confirmation_truncation_text(max_words: int) -> str:
    if max_words == 1:
        return "Confirm."

    words = ("Please", "confirm", "this", "change")
    return f"{' '.join(words[:max_words])}."


def _model_info_from_payload(value: object) -> LocalModelInfo:
    if not isinstance(value, dict):
        raise OllamaModelManagementError("Ollama model entry must be an object.")

    details = value.get("details")
    if not isinstance(details, dict):
        details = {}

    name = _required_model_string(value.get("name") or value.get("model"))
    model = _required_model_string(value.get("model") or value.get("name"))
    return LocalModelInfo(
        name=name,
        model=model,
        modified_at=_optional_string(value.get("modified_at")),
        size_bytes=_optional_int(value.get("size")),
        digest=_optional_string(value.get("digest")),
        format=_optional_string(details.get("format")),
        family=_optional_string(details.get("family")),
        families=_string_tuple(details.get("families")),
        parameter_size=_optional_string(details.get("parameter_size")),
        quantization_level=_optional_string(details.get("quantization_level")),
    )


def _model_details_from_payload(
    model: str,
    payload: dict[str, object],
) -> LocalModelDetails:
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    return LocalModelDetails(
        model=model,
        modified_at=_optional_string(payload.get("modified_at")),
        format=_optional_string(details.get("format")),
        family=_optional_string(details.get("family")),
        families=_string_tuple(details.get("families")),
        parameter_size=_optional_string(details.get("parameter_size")),
        quantization_level=_optional_string(details.get("quantization_level")),
        capabilities=_string_tuple(payload.get("capabilities")),
        parameters=_optional_string(payload.get("parameters")),
        license=_optional_string(payload.get("license")),
    )


def _download_progress_from_payload(
    payload: dict[str, object],
) -> ModelDownloadProgress:
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise OllamaModelManagementError("Ollama pull response missing status.")

    return ModelDownloadProgress(
        status=status.strip(),
        digest=_optional_string(payload.get("digest")),
        total=_optional_int(payload.get("total")),
        completed=_optional_int(payload.get("completed")),
    )


def _validated_model_name(model: str) -> str:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Model name must be a non-empty string.")
    return model.strip()


def _required_model_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OllamaModelManagementError("Ollama model entry missing model name.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )
