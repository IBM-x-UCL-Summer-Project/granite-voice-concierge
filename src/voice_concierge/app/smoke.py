"""Deterministic fake-mode smoke runner for the app pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence

from voice_concierge.app.adapter import handle_turn
from voice_concierge.app.memory import MemoryGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import ReasoningTurnContext, ReasoningTurnResult
from voice_concierge.app.serialization import JsonDict
from voice_concierge.context.types import MemoryScope
from voice_concierge.reasoning.types import MemoryAction, ReasoningResponse


class SmokeReasoningService:
    """Deterministic reasoning service for manual app-pipeline smoke checks."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        """Return a predictable response for one fake transcript turn."""

        turn_context = context or ReasoningTurnContext()
        self.calls.append({"transcript": transcript, "context": turn_context})
        normalized = transcript.lower()

        if _is_memory_write_request(normalized):
            memory_content = _memory_content_from_transcript(transcript)
            return ReasoningTurnResult(
                response=ReasoningResponse(
                    spoken_response=(
                        "I can remember that. Please confirm before I save it."
                    ),
                    needs_confirmation=True,
                    proposed_memory_action=MemoryAction(
                        action="store",
                        content=memory_content,
                        rationale="Smoke runner detected a remember request.",
                    ),
                    confidence="high",
                )
            )

        if turn_context.memories:
            return ReasoningTurnResult(
                response=ReasoningResponse(
                    spoken_response=(
                        "I found this in local memory: " f"{turn_context.memories[0]}"
                    ),
                    confidence="high",
                )
            )

        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response=f"Fake pipeline response for: {transcript}",
                confidence="high",
            )
        )


class SmokeMemoryGateway:
    """In-memory gateway used only by the fake smoke runner."""

    def __init__(self) -> None:
        self.memories: list[str] = []

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        if scope == "none":
            return ()
        return tuple(reversed(self.memories[-limit:]))

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        if scope == "none":
            return False, "memory_scope_none"
        if action.action != "store":
            return False, f"unsupported_smoke_memory_action: {action.action}"

        self.memories.append(action.content)
        return True, "stored_in_smoke_memory"


def build_smoke_pipeline() -> VoiceConciergePipeline:
    """Build a pipeline that needs no model, audio, or persistent memory setup."""

    memory: MemoryGateway = SmokeMemoryGateway()
    return VoiceConciergePipeline(
        SmokeReasoningService(),
        memory=memory,
    )


def run_smoke_turns(transcripts: Iterable[str]) -> list[JsonDict]:
    """Run fake transcript turns through the serialized app adapter."""

    pipeline = build_smoke_pipeline()
    state: JsonDict | None = None
    turns: list[JsonDict] = []

    for transcript in transcripts:
        request_payload: JsonDict = {
            "transcript": transcript,
            "state": state,
            "options": {
                "synthesize": False,
                "play": False,
            },
        }
        response_payload = handle_turn(request_payload, pipeline)
        turns.append(
            {
                "request": request_payload,
                "response": response_payload,
            }
        )
        state = response_payload["state"]

    return turns


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fake app pipeline smoke check from the command line."""

    parser = argparse.ArgumentParser(
        description="Run deterministic fake app-pipeline transcript turns.",
    )
    parser.add_argument(
        "transcripts",
        nargs="+",
        help="One or more transcript turns to run in order.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )
    args = parser.parse_args(argv)

    payload = {"turns": run_smoke_turns(args.transcripts)}
    if args.compact:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _memory_content_from_transcript(transcript: str) -> str:
    normalized = transcript.strip()
    lowered = normalized.lower()
    prefixes = ("remember that ", "remember ")
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _is_memory_write_request(normalized_transcript: str) -> bool:
    return normalized_transcript.startswith(("remember that ", "remember "))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
