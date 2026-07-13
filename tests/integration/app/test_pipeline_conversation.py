"""Integration coverage for serialized short-term conversation continuity."""

from __future__ import annotations

import pytest

from voice_concierge.app.adapter import handle_turn
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import (
    ReasoningTurnContext,
    ReasoningTurnResult,
)
from voice_concierge.reasoning.types import ReasoningResponse


class FollowUpReasoning:
    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        summary = context.conversation_summary if context is not None else None
        if transcript == "When was she born?" and summary and "Ada Lovelace" in summary:
            response = "She was born in 1815."
        else:
            response = "Ada Lovelace was an early computing pioneer."
        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response=response,
                confidence="high",
            )
        )


@pytest.mark.integration
def test_serialized_state_supplies_prior_turn_to_follow_up_reasoning() -> None:
    pipeline = VoiceConciergePipeline(FollowUpReasoning())

    first = handle_turn(
        {
            "transcript": "Who is Ada Lovelace?",
            "state": None,
        },
        pipeline,
    )
    second = handle_turn(
        {
            "transcript": "When was she born?",
            "state": first["state"],
        },
        pipeline,
    )

    assert second["spoken_response"] == "She was born in 1815."
    assert len(second["state"]["conversation_history"]) == 2
