"""Tests for source- and freshness-based information policy decisions."""

from __future__ import annotations

import pytest

from voice_concierge.reasoning.information_policy import decide_information_policy
from voice_concierge.reasoning.types import (
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
)


@pytest.mark.parametrize(
    ("source", "freshness", "expected_disposition"),
    (
        ("none", "not_required", "allow"),
        ("user_input", "not_required", "allow"),
        ("stable_knowledge", "not_required", "allow"),
        ("external_live", "current", "external_source_unavailable_offline"),
        ("runtime_live", "current", "runtime_source_unavailable"),
        ("stable_knowledge", "current", "unsupported_current_claim"),
    ),
)
def test_information_policy_uses_declared_source_not_transcript_words(
    source,
    freshness,
    expected_disposition,
) -> None:
    decision = decide_information_policy(
        ReasoningRequest(transcript="Any wording can express this intent."),
        ReasoningResponse(
            spoken_response="Candidate answer.",
            required_information_source=source,
            freshness_requirement=freshness,
        ),
    )

    assert decision.disposition == expected_disposition


def test_information_policy_requires_declared_local_context() -> None:
    decision = decide_information_policy(
        ReasoningRequest(transcript="Use my saved details."),
        ReasoningResponse(
            spoken_response="Candidate answer.",
            required_information_source="local_context",
        ),
    )

    assert decision.disposition == "missing_local_context"


def test_information_policy_allows_supplied_local_context_with_current_caveat() -> None:
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="Use my saved details.",
            memories=("Saved status: delayed.",),
        ),
        ReasoningResponse(
            spoken_response="The saved status is delayed.",
            required_information_source="local_context",
            freshness_requirement="current",
        ),
    )

    assert decision.allowed is True
    assert decision.needs_freshness_caveat is True
    assert decision.attribution_prefix == "According to your local information:"


def test_information_policy_allows_external_source_when_offline_is_disabled() -> None:
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="Use current external data.",
            constraints=ReasoningConstraints(offline=False),
        ),
        ReasoningResponse(
            spoken_response="Caller-provided current answer.",
            required_information_source="external_live",
            freshness_requirement="current",
        ),
    )

    assert decision.allowed is True
