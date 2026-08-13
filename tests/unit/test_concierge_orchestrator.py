import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.support import memory_reference
from voice_concierge.context import ContextState
from voice_concierge.memory import MemoryOperationOutcome, MemoryOperationStatus
from voice_concierge.orchestration import ConciergeOrchestrator
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    ReasoningResponse,
)


class RecordingMemoryGateway:
    def __init__(
        self,
        memories: tuple[MemoryReference, ...] = (memory_reference("prefers tea"),),
    ) -> None:
        self.memories = memories
        self.retrieve_calls: list[tuple[str, str, int]] = []
        self.apply_calls: list[tuple[MemoryAction, str]] = []
        self.apply_result = MemoryOperationOutcome(
            MemoryOperationStatus.STORED_SUCCESSFULLY
        )

    def retrieve(
        self,
        query: str,
        scope: str,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        self.retrieve_calls.append((query, scope, limit))
        return self.memories

    def apply(self, action: MemoryAction, scope: str) -> MemoryOperationOutcome:
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


class FailingMemoryGateway(RecordingMemoryGateway):
    def retrieve(
        self,
        query: str,
        scope: str,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        raise RuntimeError("memory unavailable")


class FailingReasoningEngine(RecordingReasoningEngine):
    def generate(self, request):
        self.requests.append(request)
        raise RuntimeError("reasoning unavailable")


class FailingSpeechGateway(RecordingSpeechGateway):
    def speak(self, text: str, pace: str) -> bool:
        self.speak_calls.append((text, pace))
        return False


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
        self.assertEqual(request.memories, (memory_reference("prefers tea"),))
        self.assertEqual(request.constraints.max_words, 60)
        self.assertTrue(request.constraints.allow_memory_writes)
        self.assertEqual(speech.speak_calls, [("Here is a useful answer.", "normal")])

    def test_driving_mode_request_speaks_confirmation_without_dependencies(
        self,
    ) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("Switch to driving mode")

        self.assertTrue(result.context_decision.needs_confirmation)
        self.assertIn("Driving mode", result.spoken_response)
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])
        self.assertEqual(speech.speak_calls, [(result.spoken_response, "normal")])

    def test_confirming_pending_driving_mode_acknowledges_without_reasoning(
        self,
    ) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        orchestrator.handle_transcript("Switch to driving mode")
        result = orchestrator.handle_transcript("yes")

        self.assertEqual(result.context_decision.policy.mode, "driving")
        self.assertEqual(
            result.spoken_response,
            "Driving mode activated. I'll keep responses very short and safety-aware.",
        )
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])
        self.assertEqual(speech.speak_calls[-1], (result.spoken_response, "normal"))

    def test_repeat_reuses_previous_spoken_response_without_dependencies(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )
        first = orchestrator.handle_transcript("What did we decide yesterday?")

        result = orchestrator.handle_transcript("repeat that")

        self.assertEqual(result.spoken_response, first.spoken_response)
        self.assertEqual(len(memory.retrieve_calls), 1)
        self.assertEqual(len(reasoning.requests), 1)
        self.assertEqual(speech.speak_calls[-1], (first.spoken_response, "normal"))

    def test_stop_calls_speech_stop_without_memory_or_reasoning(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("stop speaking")

        self.assertEqual(result.spoken_response, "Okay, I'll stop.")
        self.assertTrue(result.speech_succeeded)
        self.assertEqual(speech.stop_calls, 1)
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])

    def test_memory_action_is_pending_until_user_confirms(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="I'll remember that after you confirm.",
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
            initial_state=ContextState(mode="shopping"),
        )

        result = orchestrator.handle_transcript("Add oat milk to my shopping list")

        self.assertEqual(
            result.spoken_response,
            "I'll remember that after you confirm.",
        )
        self.assertEqual(memory.apply_calls, [])
        self.assertFalse(result.memory_operation.attempted)

    def test_confirmed_memory_action_is_applied_and_cleared(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="I'll remember that after you confirm.",
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
            initial_state=ContextState(mode="shopping"),
        )
        orchestrator.handle_transcript("Add oat milk to my shopping list")

        result = orchestrator.handle_transcript("yes")

        self.assertEqual(memory.apply_calls, [(action, "list_relevant")])
        self.assertTrue(result.memory_operation.attempted)
        self.assertTrue(result.memory_operation.succeeded)
        self.assertEqual(result.memory_operation.reason, "stored_successfully")
        self.assertEqual(result.spoken_response, "I've saved that.")

    def test_memory_action_cancellation_discards_pending_action(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="I'll remember that after you confirm.",
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )
        orchestrator.handle_transcript("Remember that I like oat milk")

        result = orchestrator.handle_transcript("never mind")

        self.assertEqual(memory.apply_calls, [])
        self.assertEqual(result.spoken_response, "Okay, I won't save that.")

    def test_ambiguous_reply_preserves_pending_memory_and_requests_clarification(
        self,
    ) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="I'll remember that after you confirm.",
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )
        orchestrator.handle_transcript("Remember that I like oat milk")

        result = orchestrator.handle_transcript("yesterday")

        self.assertEqual(memory.apply_calls, [])
        self.assertEqual(result.spoken_response, "Sorry, was that a yes or a no?")
        self.assertEqual(len(reasoning.requests), 1)

    def test_failed_memory_action_is_retained_for_retry(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        memory.apply_result = MemoryOperationOutcome(
            MemoryOperationStatus.STORAGE_ERROR
        )
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="I'll remember that after you confirm.",
                needs_confirmation=True,
                proposed_memory_action=action,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )
        orchestrator.handle_transcript("Remember that I like oat milk")

        failed = orchestrator.handle_transcript("yes")
        retried = orchestrator.handle_transcript("yes")

        self.assertEqual(len(memory.apply_calls), 2)
        self.assertIn("memory_action_failed", failed.errors)
        self.assertIn("memory_action_failed", retried.errors)

    def test_cooking_next_step_forwards_task_scope_and_word_limit(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
            initial_state=ContextState(mode="cooking"),
        )

        result = orchestrator.handle_transcript("what is the next step")

        self.assertEqual(result.context_decision.command_action, "next_step")
        self.assertEqual(
            memory.retrieve_calls,
            [("what is the next step", "task_relevant_only", 3)],
        )
        self.assertEqual(reasoning.requests[0].mode, "cooking")
        self.assertEqual(reasoning.requests[0].constraints.max_words, 55)
        self.assertTrue(reasoning.requests[0].constraints.allow_memory_writes)

    def test_shopping_mode_forwards_list_scope_and_word_limit(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
            initial_state=ContextState(mode="shopping"),
        )

        result = orchestrator.handle_transcript("add milk")

        self.assertEqual(result.context_decision.policy.mode, "shopping")
        self.assertEqual(memory.retrieve_calls, [("add milk", "list_relevant", 3)])
        self.assertEqual(reasoning.requests[0].constraints.max_words, 50)

    def test_driving_mode_skips_memory_and_disables_memory_writes(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
            initial_state=ContextState(mode="driving"),
        )

        result = orchestrator.handle_transcript("read the next direction")

        self.assertEqual(result.context_decision.policy.mode, "driving")
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests[0].constraints.max_words, 25)
        self.assertFalse(reasoning.requests[0].constraints.allow_memory_writes)

    def test_accessibility_preferences_affect_reasoning_and_speech(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript(
            "Keep answers short and answer more slowly"
        )

        self.assertEqual(reasoning.requests[0].constraints.max_words, 45)
        self.assertEqual(result.context_decision.policy.speech_pace, "slow")
        self.assertEqual(speech.speak_calls[-1], ("Here is a useful answer.", "slow"))

    def test_empty_transcript_returns_recoverable_result(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("   ")

        self.assertEqual(
            result.spoken_response,
            "I didn't catch that. Could you say it again?",
        )
        self.assertIn("empty_transcript", result.errors)
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])

    def test_memory_retrieval_failure_continues_to_reasoning(self) -> None:
        memory = FailingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("What did we decide yesterday?")

        self.assertIn("memory_retrieval_failed", result.errors)
        self.assertEqual(reasoning.requests[0].memories, ())
        self.assertEqual(result.spoken_response, "Here is a useful answer.")

    def test_reasoning_failure_still_attempts_speech_with_fallback(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = FailingReasoningEngine()
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("What did we decide yesterday?")

        self.assertIn("reasoning_failed", result.errors)
        self.assertEqual(
            result.spoken_response,
            "Local reasoning failed unexpectedly.",
        )
        self.assertEqual(speech.speak_calls[-1], (result.spoken_response, "normal"))

    def test_speech_failure_records_error_but_returns_text(self) -> None:
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine()
        speech = FailingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )

        result = orchestrator.handle_transcript("What did we decide yesterday?")

        self.assertFalse(result.speech_succeeded)
        self.assertIn("speech_failed", result.errors)
        self.assertEqual(result.spoken_response, "Here is a useful answer.")


if __name__ == "__main__":
    unittest.main()
