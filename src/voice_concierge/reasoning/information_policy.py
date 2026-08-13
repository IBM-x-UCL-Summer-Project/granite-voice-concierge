"""Policy decisions for information provenance and freshness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from voice_concierge.reasoning.types import (
    InformationEvidence,
    ReasoningRequest,
    ReasoningResponse,
)

InformationDisposition = Literal[
    "allow",
    "missing_user_input_evidence",
    "invalid_user_input_evidence",
    "missing_local_context",
    "missing_local_context_evidence",
    "invalid_local_context_evidence",
    "missing_runtime_context_evidence",
    "invalid_runtime_context_evidence",
    "unexpected_information_evidence",
    "runtime_source_unavailable",
    "external_source_unavailable_offline",
    "live_source_requires_current_freshness",
    "unsupported_current_claim",
]


@dataclass(frozen=True)
class InformationPolicyDecision:
    """Result of checking whether a response can use its declared source."""

    disposition: InformationDisposition
    spoken_response: str | None = None
    needs_freshness_caveat: bool = False
    attribution_prefix: str | None = None

    @property
    def allowed(self) -> bool:
        """Return whether the declared source is available for this turn."""

        return self.disposition == "allow"


def decide_information_policy(
    request: ReasoningRequest,
    response: ReasoningResponse,
) -> InformationPolicyDecision:
    """Validate declared information provenance against available capabilities."""

    source = response.required_information_source
    freshness = response.freshness_requirement
    has_local_context = bool(request.memories or request.conversation_summary)

    if source == "user_input" and not response.information_evidence:
        return InformationPolicyDecision(
            disposition="missing_user_input_evidence",
            spoken_response=(
                "I could not verify which part of your request supports that answer."
            ),
        )

    if source == "user_input" and not all(
        _is_supplied_user_input_evidence(request, evidence)
        for evidence in response.information_evidence
    ):
        return InformationPolicyDecision(
            disposition="invalid_user_input_evidence",
            spoken_response=(
                "I could not verify which part of your request supports that answer."
            ),
        )

    if source == "local_context" and not has_local_context:
        return InformationPolicyDecision(
            disposition="missing_local_context",
            spoken_response=(
                "I do not have the local information needed to answer that."
            ),
        )

    if source == "local_context" and not response.information_evidence:
        return InformationPolicyDecision(
            disposition="missing_local_context_evidence",
            spoken_response=(
                "I could not verify which local information supports that answer."
            ),
        )

    if source == "local_context" and not all(
        _is_supplied_local_evidence(request, evidence)
        for evidence in response.information_evidence
    ):
        return InformationPolicyDecision(
            disposition="invalid_local_context_evidence",
            spoken_response=(
                "I could not verify which local information supports that answer."
            ),
        )

    if source == "runtime_live" and not request.runtime_context:
        return InformationPolicyDecision(
            disposition="runtime_source_unavailable",
            spoken_response="I do not have live device information for that request.",
        )

    if source == "runtime_live" and not response.information_evidence:
        return InformationPolicyDecision(
            disposition="missing_runtime_context_evidence",
            spoken_response=(
                "I could not verify which device information supports that answer."
            ),
        )

    if source == "runtime_live" and not all(
        _is_supplied_runtime_evidence(request, evidence)
        for evidence in response.information_evidence
    ):
        return InformationPolicyDecision(
            disposition="invalid_runtime_context_evidence",
            spoken_response=(
                "I could not verify which device information supports that answer."
            ),
        )

    if source not in {"user_input", "local_context", "runtime_live"} and (
        response.information_evidence
    ):
        return InformationPolicyDecision(
            disposition="unexpected_information_evidence",
            spoken_response=(
                "I could not verify the information source for that answer."
            ),
        )

    if source in {"runtime_live", "external_live"} and freshness != "current":
        return InformationPolicyDecision(
            disposition="live_source_requires_current_freshness",
            spoken_response="I could not verify the freshness of that answer.",
        )

    if source == "external_live" and request.constraints.offline:
        return InformationPolicyDecision(
            disposition="external_source_unavailable_offline",
            spoken_response="I cannot verify up-to-date information offline.",
        )

    if freshness == "current" and source in {"none", "stable_knowledge"}:
        return InformationPolicyDecision(
            disposition="unsupported_current_claim",
            spoken_response="I cannot verify current information from that source.",
        )

    current_supplied_source = freshness == "current" and source in {
        "local_context",
        "user_input",
    }
    attribution_prefix = None
    if current_supplied_source:
        attribution_prefix = (
            "According to your local information:"
            if source == "local_context"
            else "Based on what you told me:"
        )

    return InformationPolicyDecision(
        disposition="allow",
        needs_freshness_caveat=current_supplied_source,
        attribution_prefix=attribution_prefix,
    )


def _is_supplied_user_input_evidence(
    request: ReasoningRequest,
    evidence: object,
) -> bool:
    """Return whether one citation is a verbatim current-transcript fragment."""

    return bool(
        isinstance(evidence, InformationEvidence)
        and evidence.source == "user_input"
        and _contains_quote(request.transcript, evidence.quote)
    )


def _is_supplied_local_evidence(request: ReasoningRequest, evidence: object) -> bool:
    """Return whether one citation exactly identifies supplied local context."""

    if not isinstance(evidence, InformationEvidence):
        return False

    if evidence.source == "conversation_summary":
        return bool(
            request.conversation_summary
            and _contains_quote(request.conversation_summary, evidence.quote)
        )

    for memory in request.memories:
        if (
            memory.memory_id == evidence.memory_id
            and memory.revision == evidence.memory_revision
            and _contains_quote(memory.content, evidence.quote)
        ):
            return True
    return False


def _is_supplied_runtime_evidence(
    request: ReasoningRequest,
    evidence: object,
) -> bool:
    """Return whether one citation exactly identifies supplied runtime context."""

    if not isinstance(evidence, InformationEvidence):
        return False
    if evidence.source != "runtime_context":
        return False

    return any(
        runtime_reference.runtime_id == evidence.runtime_id
        and runtime_reference.observed_at == evidence.observed_at
        and _contains_quote(runtime_reference.content, evidence.quote)
        for runtime_reference in request.runtime_context
    )


def _contains_quote(source: str, quote: str) -> bool:
    """Return whether a quote is a verbatim fragment of supplied context."""

    return quote in source
