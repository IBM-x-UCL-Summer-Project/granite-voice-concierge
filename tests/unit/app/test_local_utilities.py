"""Tests for deterministic offline assistant utilities."""

from __future__ import annotations

import pytest

from voice_concierge.app.local_utilities import (
    resolve_conversation_fact,
    resolve_local_utility,
)
from voice_concierge.app.types import ConversationTurn


@pytest.mark.parametrize(
    "transcript",
    (
        "Flip a coin",
        "Could you toss the coin?",
        "Heads or tails?",
    ),
)
def test_coin_flip_executes_locally(transcript: str) -> None:
    assert resolve_local_utility(transcript, randbelow=lambda _: 0) == "It's heads."
    assert resolve_local_utility(transcript, randbelow=lambda _: 1) == "It's tails."


def test_dice_roll_supports_common_and_polyhedral_dice() -> None:
    assert resolve_local_utility("Roll a die", randbelow=lambda _: 3) == (
        "You rolled 4."
    )
    assert resolve_local_utility("Roll 2 d20", randbelow=lambda _: 9) == (
        "You rolled 10, 10. The total is 20."
    )


def test_random_number_normalizes_reversed_bounds() -> None:
    assert (
        resolve_local_utility(
            "Pick a random number between 10 and 5",
            randbelow=lambda _: 2,
        )
        == "I picked 7."
    )


def test_unrelated_request_continues_to_reasoning() -> None:
    assert resolve_local_utility("Explain how a coin toss works") is None
    assert resolve_local_utility("What happens if I flip a coin?") is None
    assert resolve_local_utility("What is fire?") is None
    assert resolve_local_utility("What is a gas leak?") is None
    assert resolve_local_utility("What causes chest pain?") is None


@pytest.mark.parametrize(
    ("transcript", "expected_phrase"),
    (
        ("I smell gas in my home", "Leave the building immediately"),
        ("My kitchen is on fire", "stay outside"),
        ("I have chest pain", "Call emergency services now"),
    ),
)
def test_urgent_safety_requests_cannot_be_degraded_by_model_metadata(
    transcript: str,
    expected_phrase: str,
) -> None:
    response = resolve_local_utility(transcript)

    assert response is not None
    assert expected_phrase in response


def test_pipeline_does_not_call_model_for_coin_flip() -> None:
    from voice_concierge.app.pipeline import VoiceConciergePipeline
    from voice_concierge.app.smoke import SmokeReasoningService

    reasoning = SmokeReasoningService()
    result = VoiceConciergePipeline(reasoning).process_transcript("Flip a coin")

    assert result.spoken_response in {"It's heads.", "It's tails."}
    assert reasoning.calls == []


def test_explicit_short_term_fact_is_recalled_without_model_citation() -> None:
    history = (
        ConversationTurn(
            user_transcript="For this conversation only, my code word is amber.",
            assistant_response="Understood.",
        ),
    )

    assert resolve_conversation_fact("What is my code word?", history) == (
        "Your code word is amber."
    )


def test_conversation_fact_requires_an_exact_recent_label() -> None:
    history = (
        ConversationTurn(
            user_transcript="My code word is amber.",
            assistant_response="Understood.",
        ),
    )

    assert resolve_conversation_fact("What is my door code?", history) is None


def test_pipeline_recalls_explicit_short_term_fact_without_reasoning() -> None:
    from voice_concierge.app.pipeline import VoiceConciergePipeline
    from voice_concierge.app.smoke import SmokeReasoningService

    reasoning = SmokeReasoningService()
    pipeline = VoiceConciergePipeline(reasoning)
    first = pipeline.process_transcript(
        "For this conversation only, my code word is amber."
    )
    reasoning.calls.clear()

    recalled = pipeline.process_transcript("What is my code word?", first.state)

    assert recalled.spoken_response == "Your code word is amber."
    assert reasoning.calls == []
