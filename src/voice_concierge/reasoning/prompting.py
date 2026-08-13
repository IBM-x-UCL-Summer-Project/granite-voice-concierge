"""Versioned prompt rendering for local Granite reasoning backends."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from importlib.resources.abc import Traversable
from string import Template
from types import MappingProxyType
from typing import Literal

from voice_concierge.reasoning.types import (
    MemoryReference,
    ReasoningRequest,
    RuntimeReference,
)

Role = Literal["system", "user", "assistant"]

DEFAULT_PROMPT_VERSION = "v2"
PROMPT_TEMPLATE_SCHEMA_VERSION = 1
_RESOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SYSTEM_FIELDS = frozenset(
    {
        "allow_memory_writes",
        "max_words",
        "mode_policy",
        "voice_first",
    }
)
_USER_FIELDS = frozenset(
    {
        "conversation_summary",
        "memories",
        "mode",
        "runtime_context",
        "transcript",
    }
)
_MAX_TRANSCRIPT_CHARS = 1000
_MAX_SUMMARY_CHARS = 4000


class PromptTemplateError(ValueError):
    """Raised when a bundled prompt template is missing or invalid."""


@dataclass(frozen=True)
class PromptTemplate:
    """Validated prompt metadata and template text for one version."""

    prompt_id: str
    version: str
    default_mode: str
    mode_policies: Mapping[str, str]
    system_template: str
    user_template: str


@dataclass(frozen=True)
class ChatMessage:
    """A generic chat message for local model runners."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        """Return a runner-friendly dictionary representation."""

        return {"role": self.role, "content": self.content}


@lru_cache(maxsize=None)
def load_prompt_template(version: str = DEFAULT_PROMPT_VERSION) -> PromptTemplate:
    """Load and validate one bundled prompt-template version."""

    _validate_resource_name(version, label="Prompt version")
    directory = resources.files("voice_concierge.reasoning").joinpath(
        "prompts",
        version,
    )
    manifest = _load_manifest(directory, version)

    schema_version = manifest.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != PROMPT_TEMPLATE_SCHEMA_VERSION
    ):
        raise PromptTemplateError(
            f"Unsupported prompt template schema version: {schema_version!r}"
        )

    prompt_id = _required_string(manifest, "prompt_id")
    manifest_version = _required_string(manifest, "version")
    if manifest_version != version:
        raise PromptTemplateError(
            f"Prompt manifest version {manifest_version!r} does not match "
            f"directory {version!r}."
        )

    default_mode = _required_string(manifest, "default_mode").lower()
    mode_policies = _load_mode_policies(manifest)
    if default_mode not in mode_policies:
        raise PromptTemplateError(
            f"Default prompt mode {default_mode!r} has no policy entry."
        )

    system_filename = _required_string(manifest, "system_template")
    user_filename = _required_string(manifest, "user_template")
    system_template = _load_template_file(directory, system_filename)
    user_template = _load_template_file(directory, user_filename)
    _validate_template_fields(system_template, _SYSTEM_FIELDS, label="System")
    _validate_template_fields(user_template, _USER_FIELDS, label="User")

    return PromptTemplate(
        prompt_id=prompt_id,
        version=manifest_version,
        default_mode=default_mode,
        mode_policies=MappingProxyType(mode_policies),
        system_template=system_template,
        user_template=user_template,
    )


def build_granite_messages(
    request: ReasoningRequest,
    *,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> tuple[ChatMessage, ...]:
    """Render one versioned system/user message pair for a reasoning request."""

    prompt = load_prompt_template(prompt_version)
    mode = request.mode.lower()
    mode_policy = prompt.mode_policies.get(
        mode,
        prompt.mode_policies[prompt.default_mode],
    )
    system_content = Template(prompt.system_template).substitute(
        allow_memory_writes=request.constraints.allow_memory_writes,
        max_words=request.constraints.max_words,
        mode_policy=mode_policy,
        voice_first=request.constraints.voice_first,
    )
    user_content = Template(prompt.user_template).substitute(
        conversation_summary=_format_conversation_summary(request),
        memories=_format_memories(request.memories),
        mode=request.mode,
        runtime_context=_format_runtime_context(request.runtime_context),
        transcript=_format_transcript(request.transcript),
    )
    return (
        ChatMessage(role="system", content=system_content),
        ChatMessage(role="user", content=user_content),
    )


def _load_manifest(directory: Traversable, version: str) -> dict[str, object]:
    manifest_path = directory.joinpath("manifest.toml")
    try:
        content = manifest_path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise PromptTemplateError(
            f"Prompt template version {version!r} is not available."
        ) from exc

    try:
        manifest = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise PromptTemplateError(
            f"Prompt template manifest for {version!r} is invalid TOML."
        ) from exc
    return manifest


def _load_mode_policies(manifest: dict[str, object]) -> dict[str, str]:
    raw_modes = manifest.get("modes")
    if not isinstance(raw_modes, dict) or not raw_modes:
        raise PromptTemplateError("Prompt manifest must define mode policies.")

    modes: dict[str, str] = {}
    for raw_mode, raw_policy in raw_modes.items():
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            raise PromptTemplateError("Prompt mode names must be non-empty strings.")
        if not isinstance(raw_policy, str) or not raw_policy.strip():
            raise PromptTemplateError(
                f"Prompt policy for mode {raw_mode!r} must be a non-empty string."
            )
        modes[raw_mode.strip().lower()] = raw_policy.strip()
    return modes


def _load_template_file(directory: Traversable, filename: str) -> str:
    _validate_resource_name(filename, label="Prompt template filename")
    try:
        content = directory.joinpath(filename).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise PromptTemplateError(
            f"Prompt template file {filename!r} is not available."
        ) from exc
    if not content:
        raise PromptTemplateError(f"Prompt template file {filename!r} is empty.")
    return content


def _validate_template_fields(
    template_text: str,
    expected_fields: frozenset[str],
    *,
    label: str,
) -> None:
    template = Template(template_text)
    if not template.is_valid():
        raise PromptTemplateError(f"{label} prompt template syntax is invalid.")

    actual_fields = set(template.get_identifiers())
    missing_fields = sorted(expected_fields - actual_fields)
    unknown_fields = sorted(actual_fields - expected_fields)
    if missing_fields or unknown_fields:
        details = []
        if missing_fields:
            details.append(f"missing {', '.join(missing_fields)}")
        if unknown_fields:
            details.append(f"unknown {', '.join(unknown_fields)}")
        raise PromptTemplateError(
            f"{label} prompt template fields are invalid: {'; '.join(details)}."
        )


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PromptTemplateError(
            f"Prompt manifest field {key!r} must be a non-empty string."
        )
    return value.strip()


def _validate_resource_name(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not _RESOURCE_NAME_PATTERN.fullmatch(value):
        raise PromptTemplateError(f"{label} {value!r} is invalid.")


def _format_transcript(transcript: str) -> str:
    if len(transcript) > _MAX_TRANSCRIPT_CHARS:
        return transcript[:_MAX_TRANSCRIPT_CHARS] + "... [truncated]"
    return transcript


def _format_runtime_context(
    runtime_context: tuple[RuntimeReference, ...],
) -> str:
    if not runtime_context:
        return "No runtime context supplied."
    return "\n".join(
        (
            f"- id={reference.runtime_id}; observed_at={reference.observed_at}; "
            f"content={reference.content}"
        )
        for reference in runtime_context
    )


def _format_conversation_summary(request: ReasoningRequest) -> str:
    if request.conversation_summary:
        summary = request.conversation_summary
        if len(summary) > _MAX_SUMMARY_CHARS:
            return "... [truncated]\n" + summary[-_MAX_SUMMARY_CHARS:]
        return summary
    return "No summary supplied."


def _format_memories(memories: tuple[MemoryReference, ...]) -> str:
    if not memories:
        return "No local memories supplied."
    return "\n".join(_format_memory_reference(memory) for memory in memories)


def _format_memory_reference(memory: MemoryReference) -> str:
    key = memory.memory_key if memory.memory_key is not None else "none"
    topic = memory.topic if memory.topic is not None else "none"
    return (
        f"- id={memory.memory_id}; revision={memory.revision}; key={key}; "
        f"layer={memory.layer}; topic={topic}; content={memory.content}"
    )
