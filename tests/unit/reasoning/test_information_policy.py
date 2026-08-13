"""Tests for source- and freshness-based information policy decisions."""

from __future__ import annotations

import pytest

from tests.support import memory_reference
from voice_concierge.reasoning.information_policy import decide_information_policy
from voice_concierge.reasoning.types import (
    InformationEvidence,
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
    saved_status = memory_reference("Saved status: delayed.")
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="Use my saved details.",
            memories=(saved_status,),
        ),
        ReasoningResponse(
            spoken_response="The saved status is delayed.",
            required_information_source="local_context",
            information_evidence=(saved_status.information_evidence(),),
            freshness_requirement="current",
        ),
    )

    assert decision.allowed is True
    assert decision.needs_freshness_caveat is True
    assert decision.attribution_prefix == "According to your local information:"


def test_information_policy_rejects_local_context_without_evidence() -> None:
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="Use my saved details.",
            memories=(memory_reference("Saved status: delayed."),),
        ),
        ReasoningResponse(
            spoken_response="The saved status is delayed.",
            required_information_source="local_context",
        ),
    )

    assert decision.disposition == "missing_local_context_evidence"


@pytest.mark.parametrize(
    "evidence",
    (
        InformationEvidence(
            source="memory",
            quote="Saved status: delayed.",
            memory_id=999,
            memory_revision=1,
        ),
        InformationEvidence(
            source="memory",
            quote="Saved status: delayed.",
            memory_id=1,
            memory_revision=2,
        ),
        InformationEvidence(
            source="memory",
            quote="Appointment is tomorrow.",
            memory_id=1,
            memory_revision=1,
        ),
    ),
)
def test_information_policy_rejects_unverifiable_memory_evidence(
    evidence: InformationEvidence,
) -> None:
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="Use my saved details.",
            memories=(memory_reference("Saved status: delayed."),),
        ),
        ReasoningResponse(
            spoken_response="Candidate answer.",
            required_information_source="local_context",
            information_evidence=(evidence,),
        ),
    )

    assert decision.disposition == "invalid_local_context_evidence"


def test_information_policy_verifies_conversation_summary_evidence() -> None:
    decision = decide_information_policy(
        ReasoningRequest(
            transcript="What did we decide?",
            conversation_summary="We decided to call Pat after lunch.",
        ),
        ReasoningResponse(
            spoken_response="Call Pat after lunch.",
            required_information_source="local_context",
            information_evidence=(
                InformationEvidence(
                    source="conversation_summary",
                    quote="call Pat after lunch",
                ),
            ),
        ),
    )

    assert decision.allowed is True


def test_information_policy_rejects_local_evidence_for_other_sources() -> None:
    memory = memory_reference("Saved status: delayed.")
    decision = decide_information_policy(
        ReasoningRequest(transcript="What is a status?", memories=(memory,)),
        ReasoningResponse(
            spoken_response="A status describes a condition.",
            required_information_source="stable_knowledge",
            information_evidence=(memory.information_evidence(),),
        ),
    )

    assert decision.disposition == "unexpected_local_context_evidence"


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
