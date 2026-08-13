"""Policy decisions for information provenance and freshness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from voice_concierge.reasoning.types import ReasoningRequest, ReasoningResponse

InformationDisposition = Literal[
    "allow",
    "missing_local_context",
    "runtime_source_unavailable",
    "external_source_unavailable_offline",
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

    if source == "local_context" and not has_local_context:
        return InformationPolicyDecision(
            disposition="missing_local_context",
            spoken_response=(
                "I do not have the local information needed to answer that."
            ),
        )

    if source == "runtime_live":
        return InformationPolicyDecision(
            disposition="runtime_source_unavailable",
            spoken_response="I do not have live device information for that request.",
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
