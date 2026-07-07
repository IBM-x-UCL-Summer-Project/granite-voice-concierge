from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voice_concierge.context import ContextState
from voice_concierge.orchestration import ConciergeOrchestrator
from voice_concierge.reasoning.types import MemoryAction, ReasoningResponse


class RecordingMemoryGateway:
    def __init__(self, memories: tuple[str, ...] = ("prefers tea",)) -> None:
        self.memories = memories
        self.retrieve_calls: list[tuple[str, str, int]] = []
        self.apply_calls: list[tuple[MemoryAction, str]] = []
        self.apply_result = (True, "stored_successfully")

    def retrieve(self, query: str, scope: str, limit: int = 3) -> tuple[str, ...]:
        self.retrieve_calls.append((query, scope, limit))
        return self.memories

    def apply(self, action: MemoryAction, scope: str) -> tuple[bool, str]:
        self.apply_calls.append((action, scope))
        return self.apply_result


class RecordingReasoningEngine:
    def __init__(self, response: ReasoningResponse | None = None) -> None:
        self.response = response or ReasoningResponse(
            spoken_response="Here is a useful answer.",
            confidence="high",
        )
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return self.response


class RecordingSpeechGateway:
    def __init__(self) -> None:
        self.speak_calls: list[tuple[str, str]] = []
        self.stop_calls = 0
        self.speak_result = True

    def speak(self, text: str, pace: str) -> bool:
        self.speak_calls.append((text, pace))
        return self.speak_result

    def stop(self) -> bool:
        self.stop_calls += 1
        return True


class ConciergeOrchestratorTest(unittest.TestCase):
    def test_home_turn_retrieves_memory_calls_reasoning_and_speaks(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("What did we decide yesterday?")

        self.assertEqual(result.context_decision.policy.mode, "home")
        self.assertEqual(result.spoken_response, "Here is a useful answer.")
        self.assertIs(result.reasoning_response, reasoning.response)
        self.assertTrue(result.speech_succeeded)
        self.assertEqual(result.errors, ())
        self.assertEqual(
            memory.retrieve_calls,
            [("What did we decide yesterday?", "personal_relevant", 3)],
        )
        self.assertEqual(len(reasoning.requests), 1)
        request = reasoning.requests[0]
        self.assertEqual(request.transcript, "What did we decide yesterday?")
        self.assertEqual(request.mode, "home")
        self.assertEqual(request.memories, ("prefers tea",))
        self.assertEqual(request.constraints.max_words, 60)
        self.assertTrue(request.constraints.allow_memory_writes)
        self.assertEqual(speech.speak_calls, [("Here is a useful answer.", "normal")])


if __name__ == "__main__":
    unittest.main()
