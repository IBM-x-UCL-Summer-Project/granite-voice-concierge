# Context Orchestration Implementation Plan

> **Status:** Historical implementation plan. The original
> `ConciergeOrchestrator` API now delegates to `VoiceConciergePipeline`, which is
> the sole turn-processing implementation. New code should use the app pipeline
> directly.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable `ConciergeOrchestrator` that links context decisions to memory retrieval, local reasoning, and speech output through injected dependencies.

**Architecture:** Keep `ContextManager` pure and add a separate `voice_concierge.orchestration` package that owns turn-level composition. The orchestrator accepts a transcript, updates context state, routes deterministic commands, retrieves memory by context policy, calls the reasoning engine, handles proposed memory actions, and sends the selected response to speech. Concrete adapters wrap `MemoryManager` and `OfflineTTS`, while tests use fakes so they do not need Ollama, a database, a microphone, or speakers.

**Tech Stack:** Python 3.9+ dataclasses, `typing.Protocol`, existing `unittest` tests, existing `pytest` runner, existing `voice_concierge.context`, `voice_concierge.reasoning`, `voice_concierge.memory`, and `voice_concierge.voice_output` modules.

---

## File Structure

- Modify `src/voice_concierge/context/types.py`
  - Add the public `ConfirmationIntent` literal.
- Modify `src/voice_concierge/context/manager.py`
  - Add `detect_confirmation_intent(transcript: str) -> ConfirmationIntent | None`.
  - Reuse it in pending mode handling.
- Modify `src/voice_concierge/context/__init__.py`
  - Export `ConfirmationIntent` and `detect_confirmation_intent`.
- Create `src/voice_concierge/orchestration/types.py`
  - Define `MemoryGateway`, `SpeechGateway`, `MemoryOperationResult`, and immutable `TurnResult`.
- Create `src/voice_concierge/orchestration/orchestrator.py`
  - Implement `ConciergeOrchestrator`.
- Create `src/voice_concierge/orchestration/adapters.py`
  - Implement `MemoryManagerGateway` and `OfflineTTSSpeechGateway`.
- Create `src/voice_concierge/orchestration/__init__.py`
  - Export orchestration public API.
- Modify `src/voice_concierge/voice_output/tts_pipeline.py`
  - Add `OfflineTTS.stop()` so the speech adapter has a real stop target.
- Modify `tests/unit/test_context_manager.py`
  - Add tests for shared confirmation intent and keep pending-mode behavior covered.
- Create `tests/unit/test_concierge_orchestrator.py`
  - Cover orchestration data flow, commands, memory confirmation, and recoverable failures using fakes.
- Create `tests/unit/test_orchestration_adapters.py`
  - Cover adapter scope mapping and pace mapping without loading models or audio hardware.

## Task 1: Expose Shared Confirmation Intent from Context

**Files:**
- Modify: `src/voice_concierge/context/types.py`
- Modify: `src/voice_concierge/context/manager.py`
- Modify: `src/voice_concierge/context/__init__.py`
- Test: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing tests for confirmation intent**

Add this import in `tests/unit/test_context_manager.py`:

```python
from voice_concierge.context import (
    CommandAction,
    ConfirmationIntent,
    ContextManager,
    ContextMode,
    ContextState,
    detect_confirmation_intent,
)
```

Add these tests to `ContextManagerTest`:

```python
    def test_detect_confirmation_intent_returns_confirm_cancel_or_none(self) -> None:
        examples: dict[str, ConfirmationIntent | None] = {
            "Yes, go ahead": "confirm",
            "ok please": "confirm",
            "Never mind": "cancel",
            "cancel that": "cancel",
            "what is next": None,
        }

        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(detect_confirmation_intent(transcript), expected)

    def test_pending_mode_uses_shared_confirmation_intent(self) -> None:
        state = ContextState(mode="home", pending_mode="driving")

        decision = self.manager.handle("ok please", state)

        self.assertEqual(decision.state.mode, "driving")
        self.assertIsNone(decision.state.pending_mode)
        self.assertTrue(decision.mode_changed)
```

- [ ] **Step 2: Run the focused context test and verify it fails**

Run:

```bash
pytest tests/unit/test_context_manager.py -q
```

Expected: FAIL because `ConfirmationIntent` and `detect_confirmation_intent` are not exported yet.

- [ ] **Step 3: Add the type and function**

In `src/voice_concierge/context/types.py`, add:

```python
ConfirmationIntent = Literal["confirm", "cancel"]
```

In `src/voice_concierge/context/manager.py`, import the type:

```python
from voice_concierge.context.types import (
    AccessibilityProfile,
    CommandAction,
    ConfirmationIntent,
    ContextDecision,
    ContextMode,
    ContextState,
)
```

Add the public function near `_normalize`:

```python
def detect_confirmation_intent(transcript: str) -> ConfirmationIntent | None:
    """Return an explicit confirmation intent from a user transcript."""

    normalized = _normalize(transcript)
    if _contains_any(normalized, _CANCEL_WORDS):
        return "cancel"
    if _contains_any(normalized, _CONFIRM_WORDS):
        return "confirm"
    return None
```

Update `_handle_pending_mode`:

```python
        confirmation_intent = detect_confirmation_intent(normalized)

        if confirmation_intent == "cancel":
            cleared_state = replace(state, pending_mode=None)
            return ContextDecision(
                state=cleared_state,
                policy=policy_for_mode(cleared_state.mode, cleared_state.accessibility),
                command_action=command_action or "cancel",
            )

        if confirmation_intent == "confirm":
            target_mode = state.pending_mode
            switched_state = replace(state, mode=target_mode, pending_mode=None)
            return ContextDecision(
                state=switched_state,
                policy=policy_for_mode(target_mode, switched_state.accessibility),
                mode_changed=True,
                command_action=command_action,
            )
```

In `src/voice_concierge/context/__init__.py`, export the new names:

```python
from voice_concierge.context.manager import ContextManager, detect_confirmation_intent
from voice_concierge.context.types import (
    AccessibilityProfile,
    CommandAction,
    ConfirmationIntent,
    ContextDecision,
    ContextMode,
    ContextState,
    MemoryScope,
    ModePolicy,
    ResponseStyle,
    SpeechPace,
    Verbosity,
)
```

Add `"ConfirmationIntent"` and `"detect_confirmation_intent"` to `__all__`.

- [ ] **Step 4: Run the focused context test and verify it passes**

Run:

```bash
pytest tests/unit/test_context_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/voice_concierge/context/types.py src/voice_concierge/context/manager.py src/voice_concierge/context/__init__.py tests/unit/test_context_manager.py
git commit -m "feat: expose context confirmation intent"
```

## Task 2: Add Orchestration Public Types and Happy-Path Turn Flow

**Files:**
- Create: `src/voice_concierge/orchestration/types.py`
- Create: `src/voice_concierge/orchestration/orchestrator.py`
- Create: `src/voice_concierge/orchestration/__init__.py`
- Test: `tests/unit/test_concierge_orchestrator.py`

- [ ] **Step 1: Write failing happy-path orchestration test**

Create `tests/unit/test_concierge_orchestrator.py`:

```python
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
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: FAIL because `voice_concierge.orchestration` does not exist.

- [ ] **Step 3: Add orchestration types**

Create `src/voice_concierge/orchestration/types.py`:

```python
"""Public types and ports for turn-level orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from voice_concierge.context import ContextDecision, MemoryScope, SpeechPace
from voice_concierge.reasoning.types import MemoryAction, ReasoningResponse

TurnError = Literal[
    "empty_transcript",
    "memory_retrieval_failed",
    "reasoning_failed",
    "speech_failed",
    "memory_action_failed",
]


class MemoryGateway(Protocol):
    """Memory operations required by a single assistant turn."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        limit: int = 3,
    ) -> tuple[str, ...]:
        """Return memory snippets relevant to the query and context scope."""

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        """Apply a confirmed memory action under the active context scope."""


class SpeechGateway(Protocol):
    """Speech output operations required by the orchestrator."""

    def speak(self, text: str, pace: SpeechPace) -> bool:
        """Speak text at the requested pace."""

    def stop(self) -> bool:
        """Stop current speech output if supported."""


@dataclass(frozen=True)
class MemoryOperationResult:
    """Observable result for a memory action attempted by the orchestrator."""

    attempted: bool = False
    succeeded: bool = False
    reason: str = ""


@dataclass(frozen=True)
class TurnResult:
    """Observable result of coordinating one assistant turn."""

    context_decision: ContextDecision
    spoken_response: str
    reasoning_response: ReasoningResponse | None = None
    speech_succeeded: bool = False
    memory_operation: MemoryOperationResult = MemoryOperationResult()
    errors: tuple[TurnError, ...] = ()
```

- [ ] **Step 4: Add minimal orchestrator implementation**

Create `src/voice_concierge/orchestration/orchestrator.py`:

```python
"""Turn-level orchestration for the voice concierge."""

from __future__ import annotations

from voice_concierge.context import ContextManager, ContextState
from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.reasoning.types import ReasoningConstraints, ReasoningRequest

from voice_concierge.orchestration.types import (
    MemoryGateway,
    MemoryOperationResult,
    SpeechGateway,
    TurnError,
    TurnResult,
)

_EMPTY_TRANSCRIPT_RESPONSE = "I didn't catch that. Could you say it again?"
_REASONING_FALLBACK_RESPONSE = "Sorry, I had trouble thinking that through."


class ConciergeOrchestrator:
    """Coordinate context, memory, reasoning, and speech for one text turn."""

    def __init__(
        self,
        *,
        memory: MemoryGateway,
        reasoning: ReasoningEngine,
        speech: SpeechGateway,
        context_manager: ContextManager | None = None,
        initial_state: ContextState | None = None,
    ) -> None:
        self._memory = memory
        self._reasoning = reasoning
        self._speech = speech
        self._context_manager = context_manager or ContextManager()
        self._state = initial_state or ContextState()
        self._last_spoken_response: str | None = None

    def handle_transcript(self, transcript: str) -> TurnResult:
        """Handle one transcribed user utterance."""

        errors: list[TurnError] = []
        if not transcript.strip():
            errors.append("empty_transcript")
            decision = self._context_manager.handle("", self._state)
            self._state = decision.state
            speech_succeeded = self._speak(_EMPTY_TRANSCRIPT_RESPONSE, decision, errors)
            return TurnResult(
                context_decision=decision,
                spoken_response=_EMPTY_TRANSCRIPT_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        decision = self._context_manager.handle(transcript, self._state)
        self._state = decision.state

        memories: tuple[str, ...] = ()
        if decision.policy.memory_scope != "none":
            try:
                memories = self._memory.retrieve(
                    transcript,
                    decision.policy.memory_scope,
                    limit=3,
                )
            except Exception:
                errors.append("memory_retrieval_failed")

        try:
            reasoning_response = self._reasoning.generate(
                ReasoningRequest(
                    transcript=transcript,
                    mode=decision.policy.mode,
                    memories=memories,
                    constraints=ReasoningConstraints(
                        max_words=decision.policy.max_words,
                        allow_memory_writes=decision.policy.memory_scope != "none",
                    ),
                )
            )
            spoken_response = reasoning_response.spoken_response
        except Exception:
            errors.append("reasoning_failed")
            reasoning_response = None
            spoken_response = _REASONING_FALLBACK_RESPONSE

        speech_succeeded = self._speak(spoken_response, decision, errors)
        self._last_spoken_response = spoken_response
        return TurnResult(
            context_decision=decision,
            spoken_response=spoken_response,
            reasoning_response=reasoning_response,
            speech_succeeded=speech_succeeded,
            memory_operation=MemoryOperationResult(),
            errors=tuple(errors),
        )

    def _speak(
        self,
        text: str,
        decision,
        errors: list[TurnError],
    ) -> bool:
        try:
            succeeded = self._speech.speak(text, decision.policy.speech_pace)
        except Exception:
            errors.append("speech_failed")
            return False
        if not succeeded:
            errors.append("speech_failed")
        return succeeded
```

Create `src/voice_concierge/orchestration/__init__.py`:

```python
"""Turn-level orchestration for voice concierge modules."""

from voice_concierge.orchestration.orchestrator import ConciergeOrchestrator
from voice_concierge.orchestration.types import (
    MemoryGateway,
    MemoryOperationResult,
    SpeechGateway,
    TurnError,
    TurnResult,
)

__all__ = [
    "ConciergeOrchestrator",
    "MemoryGateway",
    "MemoryOperationResult",
    "SpeechGateway",
    "TurnError",
    "TurnResult",
]
```

- [ ] **Step 5: Run the happy-path orchestration test and verify it passes**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/voice_concierge/orchestration tests/unit/test_concierge_orchestrator.py
git commit -m "feat: add concierge orchestrator happy path"
```

## Task 3: Add Deterministic Command and Mode-Confirmation Routing

**Files:**
- Modify: `src/voice_concierge/orchestration/orchestrator.py`
- Modify: `tests/unit/test_concierge_orchestrator.py`

- [ ] **Step 1: Write failing command and mode-confirmation tests**

Add these tests to `ConciergeOrchestratorTest`:

```python
    def test_driving_mode_request_speaks_confirmation_without_dependencies(self) -> None:
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

    def test_confirming_pending_driving_mode_acknowledges_without_reasoning(self) -> None:
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
        self.assertEqual(result.spoken_response, "Driving mode is on.")
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])
        self.assertEqual(speech.speak_calls[-1], ("Driving mode is on.", "normal"))

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

        self.assertEqual(result.spoken_response, "Okay, I'll stop speaking.")
        self.assertTrue(result.speech_succeeded)
        self.assertEqual(speech.stop_calls, 1)
        self.assertEqual(memory.retrieve_calls, [])
        self.assertEqual(reasoning.requests, [])
```

- [ ] **Step 2: Run the focused orchestration tests and verify they fail**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: FAIL because deterministic command routing is not implemented.

- [ ] **Step 3: Implement deterministic routing**

Add constants to `src/voice_concierge/orchestration/orchestrator.py`:

```python
_CANCEL_RESPONSE = "Okay, cancelled."
_DRIVING_MODE_ON_RESPONSE = "Driving mode is on."
_NOTHING_TO_REPEAT_RESPONSE = "I don't have anything to repeat yet."
_STOP_RESPONSE = "Okay, I'll stop speaking."
```

After the context decision is produced in `handle_transcript`, before memory retrieval, add:

```python
        if decision.needs_confirmation:
            spoken_response = decision.confirmation_prompt
            speech_succeeded = self._speak(spoken_response, decision, errors)
            self._last_spoken_response = spoken_response
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.mode_changed and transcript.strip().lower() in {
            "yes",
            "confirm",
            "okay",
            "ok",
            "go ahead",
        }:
            spoken_response = _DRIVING_MODE_ON_RESPONSE
            speech_succeeded = self._speak(spoken_response, decision, errors)
            self._last_spoken_response = spoken_response
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "repeat":
            spoken_response = self._last_spoken_response or _NOTHING_TO_REPEAT_RESPONSE
            speech_succeeded = self._speak(spoken_response, decision, errors)
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "stop":
            try:
                speech_succeeded = self._speech.stop()
            except Exception:
                errors.append("speech_failed")
                speech_succeeded = False
            return TurnResult(
                context_decision=decision,
                spoken_response=_STOP_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "cancel":
            speech_succeeded = self._speak(_CANCEL_RESPONSE, decision, errors)
            self._last_spoken_response = _CANCEL_RESPONSE
            return TurnResult(
                context_decision=decision,
                spoken_response=_CANCEL_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )
```

Replace the literal confirmation-set check with `detect_confirmation_intent(transcript) == "confirm"` if Task 1 has already exported the function:

```python
from voice_concierge.context import (
    ContextManager,
    ContextState,
    detect_confirmation_intent,
)
```

and:

```python
        if decision.mode_changed and detect_confirmation_intent(transcript) == "confirm":
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/voice_concierge/orchestration/orchestrator.py tests/unit/test_concierge_orchestrator.py
git commit -m "feat: route deterministic orchestration commands"
```

## Task 4: Add Memory Action Confirmation Flow

**Files:**
- Modify: `src/voice_concierge/orchestration/orchestrator.py`
- Modify: `tests/unit/test_concierge_orchestrator.py`

- [ ] **Step 1: Write failing memory confirmation tests**

Add these tests to `ConciergeOrchestratorTest`:

```python
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

        self.assertEqual(result.spoken_response, "Should I remember: User likes oat milk.?")
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

    def test_unrelated_turn_implicitly_cancels_pending_memory_and_continues(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        reasoning = RecordingReasoningEngine(
            ReasoningResponse(
                spoken_response="New answer.",
                needs_confirmation=False,
                proposed_memory_action=None,
                confidence="high",
            )
        )
        speech = RecordingSpeechGateway()
        orchestrator = ConciergeOrchestrator(
            memory=memory,
            reasoning=reasoning,
            speech=speech,
        )
        orchestrator._pending_memory_action = action
        orchestrator._pending_memory_scope = "personal_relevant"

        result = orchestrator.handle_transcript("What is the weather plan?")

        self.assertEqual(memory.apply_calls, [])
        self.assertEqual(result.spoken_response, "New answer.")
        self.assertEqual(len(reasoning.requests), 1)

    def test_failed_memory_action_is_retained_for_retry(self) -> None:
        action = MemoryAction(
            action="store",
            content="User likes oat milk.",
            rationale="Preference stated by user.",
            requires_confirmation=True,
        )
        memory = RecordingMemoryGateway()
        memory.apply_result = (False, "storage_error")
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
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: FAIL because pending memory action state and confirmation handling are not implemented.

- [ ] **Step 3: Implement pending memory state and confirmation handling**

In `ConciergeOrchestrator.__init__`, add:

```python
        self._pending_memory_action = None
        self._pending_memory_scope = None
```

Import the confirmation helper and memory action type:

```python
from voice_concierge.context import (
    ContextManager,
    ContextState,
    MemoryScope,
    detect_confirmation_intent,
)
from voice_concierge.reasoning.types import MemoryAction, ReasoningConstraints, ReasoningRequest
```

Add constants:

```python
_MEMORY_CONFIRMATION_PREFIX = "Should I remember: "
_MEMORY_CANCELLED_RESPONSE = "Okay, I won't save that."
_MEMORY_SAVED_RESPONSE = "I've saved that."
_MEMORY_FAILED_RESPONSE = "I couldn't save that yet."
```

At the top of `handle_transcript`, after the empty-transcript branch and before context handling, add:

```python
        pending_result = self._handle_pending_memory_confirmation(transcript, errors)
        if pending_result is not None:
            return pending_result
```

Add helper methods:

```python
    def _handle_pending_memory_confirmation(
        self,
        transcript: str,
        errors: list[TurnError],
    ) -> TurnResult | None:
        if self._pending_memory_action is None or self._pending_memory_scope is None:
            return None

        intent = detect_confirmation_intent(transcript)
        if intent is None:
            self._pending_memory_action = None
            self._pending_memory_scope = None
            return None

        decision = self._context_manager.handle(transcript, self._state)
        self._state = decision.state

        if intent == "cancel":
            self._pending_memory_action = None
            self._pending_memory_scope = None
            speech_succeeded = self._speak(_MEMORY_CANCELLED_RESPONSE, decision, errors)
            self._last_spoken_response = _MEMORY_CANCELLED_RESPONSE
            return TurnResult(
                context_decision=decision,
                spoken_response=_MEMORY_CANCELLED_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        try:
            succeeded, reason = self._memory.apply(
                self._pending_memory_action,
                self._pending_memory_scope,
            )
        except Exception:
            succeeded = False
            reason = "exception"

        if succeeded:
            self._pending_memory_action = None
            self._pending_memory_scope = None
            spoken_response = _MEMORY_SAVED_RESPONSE
        else:
            errors.append("memory_action_failed")
            spoken_response = _MEMORY_FAILED_RESPONSE

        speech_succeeded = self._speak(spoken_response, decision, errors)
        self._last_spoken_response = spoken_response
        return TurnResult(
            context_decision=decision,
            spoken_response=spoken_response,
            speech_succeeded=speech_succeeded,
            memory_operation=MemoryOperationResult(
                attempted=True,
                succeeded=succeeded,
                reason=reason,
            ),
            errors=tuple(errors),
        )
```

After reasoning succeeds and before speech, add:

```python
        if (
            reasoning_response is not None
            and reasoning_response.proposed_memory_action is not None
            and reasoning_response.proposed_memory_action.requires_confirmation
        ):
            self._pending_memory_action = reasoning_response.proposed_memory_action
            self._pending_memory_scope = decision.policy.memory_scope
            spoken_response = (
                f"{_MEMORY_CONFIRMATION_PREFIX}"
                f"{reasoning_response.proposed_memory_action.content}?"
            )
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/voice_concierge/orchestration/orchestrator.py tests/unit/test_concierge_orchestrator.py
git commit -m "feat: confirm orchestration memory actions"
```

## Task 5: Cover Policy Modes, Accessibility, and Failure Boundaries

**Files:**
- Modify: `src/voice_concierge/orchestration/orchestrator.py`
- Modify: `tests/unit/test_concierge_orchestrator.py`

- [ ] **Step 1: Write failing policy and failure tests**

Add these helpers to `tests/unit/test_concierge_orchestrator.py`:

```python
class FailingMemoryGateway(RecordingMemoryGateway):
    def retrieve(self, query: str, scope: str, limit: int = 3) -> tuple[str, ...]:
        raise RuntimeError("memory unavailable")


class FailingReasoningEngine(RecordingReasoningEngine):
    def generate(self, request):
        self.requests.append(request)
        raise RuntimeError("reasoning unavailable")


class FailingSpeechGateway(RecordingSpeechGateway):
    def speak(self, text: str, pace: str) -> bool:
        self.speak_calls.append((text, pace))
        return False
```

Add these tests to `ConciergeOrchestratorTest`:

```python
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
        self.assertEqual(memory.retrieve_calls, [("what is the next step", "task_relevant_only", 3)])
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

        result = orchestrator.handle_transcript("Keep answers short and answer more slowly")

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

        self.assertEqual(result.spoken_response, "I didn't catch that. Could you say it again?")
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
        self.assertEqual(result.spoken_response, "Sorry, I had trouble thinking that through.")
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
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: FAIL if any policy or error behavior is still incomplete.

- [ ] **Step 3: Complete policy and recoverable-failure behavior**

Update `handle_transcript` so:

```python
        memories: tuple[str, ...] = ()
        if decision.policy.memory_scope != "none":
            try:
                memories = self._memory.retrieve(
                    transcript,
                    decision.policy.memory_scope,
                    limit=3,
                )
            except Exception:
                errors.append("memory_retrieval_failed")
```

Ensure `ReasoningRequest` uses:

```python
                    constraints=ReasoningConstraints(
                        max_words=decision.policy.max_words,
                        allow_memory_writes=decision.policy.memory_scope != "none",
                    ),
```

Ensure `_speak` records `speech_failed` exactly once per failed speech attempt:

```python
        try:
            succeeded = self._speech.speak(text, decision.policy.speech_pace)
        except Exception:
            errors.append("speech_failed")
            return False
        if not succeeded:
            errors.append("speech_failed")
        return succeeded
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
pytest tests/unit/test_concierge_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/voice_concierge/orchestration/orchestrator.py tests/unit/test_concierge_orchestrator.py
git commit -m "feat: harden orchestration policy routing"
```

## Task 6: Add Production Adapters for Memory and Speech

**Files:**
- Create: `src/voice_concierge/orchestration/adapters.py`
- Modify: `src/voice_concierge/orchestration/__init__.py`
- Modify: `src/voice_concierge/voice_output/tts_pipeline.py`
- Test: `tests/unit/test_orchestration_adapters.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/unit/test_orchestration_adapters.py`:

```python
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voice_concierge.orchestration import MemoryManagerGateway, OfflineTTSSpeechGateway
from voice_concierge.reasoning.types import MemoryAction
from voice_concierge.voice_output.tts_pipeline import OfflineTTS


class FakeMemoryManager:
    def __init__(self) -> None:
        self.retrieve_calls = []
        self.store_calls = []
        self.process_calls = []

    def retrieve_similar(self, query, top_k=5, person=None, topic=None, layer=None):
        self.retrieve_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "person": person,
                "topic": topic,
                "layer": layer,
            }
        )
        return [{"content": "remembered item"}, {"missing": "content"}]

    def store_memory(self, **kwargs):
        self.store_calls.append(kwargs)
        return True, "stored_successfully", 123

    def process_memory_action(self, action):
        self.process_calls.append(action)
        return True, "processed"


class FakeTTS:
    def __init__(self) -> None:
        self.speak_calls = []
        self.stop_calls = 0

    def speak(self, text, length_scale=1.2):
        self.speak_calls.append((text, length_scale))
        return True

    def stop(self):
        self.stop_calls += 1
        return True


class OrchestrationAdaptersTest(unittest.TestCase):
    def test_memory_gateway_maps_scopes_to_filters(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)

        self.assertEqual(gateway.retrieve("tea", "none"), ())
        self.assertEqual(gateway.retrieve("tea", "personal_relevant", limit=2), ("remembered item",))
        self.assertEqual(gateway.retrieve("recipe", "task_relevant_only"), ("remembered item",))
        self.assertEqual(gateway.retrieve("milk", "list_relevant"), ("remembered item",))

        self.assertEqual(manager.retrieve_calls[0]["topic"], None)
        self.assertEqual(manager.retrieve_calls[0]["top_k"], 2)
        self.assertEqual(manager.retrieve_calls[1]["topic"], "procedural")
        self.assertEqual(manager.retrieve_calls[2]["topic"], "shopping")

    def test_shopping_store_action_uses_shopping_topic(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)
        action = MemoryAction(
            action="store",
            content="Buy oat milk.",
            rationale="User added an item.",
            requires_confirmation=True,
        )

        result = gateway.apply(action, "list_relevant")

        self.assertEqual(result, (True, "stored_successfully"))
        self.assertEqual(
            manager.store_calls,
            [
                {
                    "content": "Buy oat milk.",
                    "layer": "feedback",
                    "topic": "shopping",
                    "validate": False,
                }
            ],
        )
        self.assertEqual(manager.process_calls, [])

    def test_non_shopping_memory_action_delegates_to_manager(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)
        action = MemoryAction(
            action="store",
            content="User likes tea.",
            rationale="Preference.",
            requires_confirmation=True,
        )

        result = gateway.apply(action, "personal_relevant")

        self.assertEqual(result, (True, "processed"))
        self.assertEqual(manager.process_calls, [action])

    def test_speech_gateway_maps_pace_to_length_scale_and_stop(self) -> None:
        tts = FakeTTS()
        gateway = OfflineTTSSpeechGateway(tts)

        self.assertTrue(gateway.speak("hello", "normal"))
        self.assertTrue(gateway.speak("slow hello", "slow"))
        self.assertTrue(gateway.stop())

        self.assertEqual(tts.speak_calls, [("hello", 1.2), ("slow hello", 1.5)])
        self.assertEqual(tts.stop_calls, 1)

    def test_offline_tts_stop_calls_sounddevice_stop(self) -> None:
        tts = OfflineTTS()

        with patch("voice_concierge.voice_output.tts_pipeline.sd.stop") as stop:
            self.assertTrue(tts.stop())

        stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
pytest tests/unit/test_orchestration_adapters.py -q
```

Expected: FAIL because adapters and `OfflineTTS.stop()` do not exist.

- [ ] **Step 3: Implement adapters**

Create `src/voice_concierge/orchestration/adapters.py`:

```python
"""Production adapters for orchestration ports."""

from __future__ import annotations

from typing import Any

from voice_concierge.context import MemoryScope, SpeechPace
from voice_concierge.reasoning.types import MemoryAction


class MemoryManagerGateway:
    """Adapt MemoryManager to the orchestrator memory port."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        limit: int = 3,
    ) -> tuple[str, ...]:
        if scope == "none":
            return ()

        topic = _topic_for_scope(scope)
        memories = self._manager.retrieve_similar(
            query,
            top_k=limit,
            topic=topic,
        )
        return tuple(
            memory["content"]
            for memory in memories
            if isinstance(memory, dict) and isinstance(memory.get("content"), str)
        )

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        if action.action == "store" and scope == "list_relevant":
            success, reason, _ = self._manager.store_memory(
                content=action.content,
                layer="feedback",
                topic="shopping",
                validate=False,
            )
            return success, reason

        return self._manager.process_memory_action(action)


class OfflineTTSSpeechGateway:
    """Adapt OfflineTTS to the orchestrator speech port."""

    def __init__(self, tts: Any) -> None:
        self._tts = tts

    def speak(self, text: str, pace: SpeechPace) -> bool:
        return self._tts.speak(text, length_scale=_length_scale_for_pace(pace))

    def stop(self) -> bool:
        return self._tts.stop()


def _topic_for_scope(scope: MemoryScope) -> str | None:
    if scope == "task_relevant_only":
        return "procedural"
    if scope == "list_relevant":
        return "shopping"
    return None


def _length_scale_for_pace(pace: SpeechPace) -> float:
    if pace == "slow":
        return 1.5
    return 1.2
```

Update `src/voice_concierge/orchestration/__init__.py`:

```python
from voice_concierge.orchestration.adapters import (
    MemoryManagerGateway,
    OfflineTTSSpeechGateway,
)
```

Add `"MemoryManagerGateway"` and `"OfflineTTSSpeechGateway"` to `__all__`.

- [ ] **Step 4: Add `OfflineTTS.stop()`**

In `src/voice_concierge/voice_output/tts_pipeline.py`, add this method inside `OfflineTTS`:

```python
    def stop(self) -> bool:
        """Stop active playback when the audio backend supports it."""
        try:
            sd.stop()
            return True
        except Exception as e:
            logging.error(f"Error stopping TTS playback: {e}")
            return False
```

- [ ] **Step 5: Run adapter tests and verify they pass**

Run:

```bash
pytest tests/unit/test_orchestration_adapters.py -q
```

Expected: PASS. If importing `sounddevice` fails in the local environment, skip only `test_offline_tts_stop_calls_sounddevice_stop` with `@unittest.skipUnless` based on import availability and keep the adapter tests active.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/voice_concierge/orchestration/adapters.py src/voice_concierge/orchestration/__init__.py src/voice_concierge/voice_output/tts_pipeline.py tests/unit/test_orchestration_adapters.py
git commit -m "feat: add orchestration production adapters"
```

## Task 7: Regression, Formatting, and Final Cleanup

**Files:**
- Review all changed files.
- No new source files unless a verification failure points to a specific defect.

- [ ] **Step 1: Run all focused unit tests**

Run:

```bash
pytest tests/unit/test_context_manager.py tests/unit/test_concierge_orchestrator.py tests/unit/test_orchestration_adapters.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full existing test suite**

Run:

```bash
pytest -q
```

Expected: PASS, or failures only in pre-existing integration tests that require unavailable audio/model hardware. If a failure is environmental, record the exact failing test name and exception.

- [ ] **Step 3: Run Ruff if available**

Run:

```bash
ruff check src/voice_concierge/context src/voice_concierge/orchestration tests/unit/test_context_manager.py tests/unit/test_concierge_orchestrator.py tests/unit/test_orchestration_adapters.py
```

Expected: PASS. If `ruff` is not installed, record `ruff: command not found`.

- [ ] **Step 4: Run Black check if available**

Run:

```bash
black --check src/voice_concierge/context src/voice_concierge/orchestration tests/unit/test_context_manager.py tests/unit/test_concierge_orchestrator.py tests/unit/test_orchestration_adapters.py
```

Expected: PASS. If `black` is not installed, record `black: command not found`.

- [ ] **Step 5: Inspect git status and diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intentional orchestration/context/test changes plus any pre-existing user changes that were present before execution.

- [ ] **Step 6: Commit final cleanup if there are formatting-only or verification-driven fixes**

Run only if Step 3 or Step 4 required edits:

```bash
git add src/voice_concierge/context src/voice_concierge/orchestration src/voice_concierge/voice_output/tts_pipeline.py tests/unit/test_context_manager.py tests/unit/test_concierge_orchestrator.py tests/unit/test_orchestration_adapters.py
git commit -m "chore: polish context orchestration"
```

Expected: commit succeeds, or there is nothing to commit.

## Self-Review

Spec coverage:

- Context confirmation intent is covered by Task 1.
- New orchestration package, dependency protocols, result types, and `ConciergeOrchestrator` are covered by Tasks 2 through 5.
- Memory scope retrieval, shopping store behavior, and speech pace mapping are covered by Task 6.
- Empty input, deterministic commands, pending mode confirmation, pending memory actions, and recoverable dependency failures are covered by Tasks 3 through 5.
- Regression, Ruff, and formatting checks are covered by Task 7.

Placeholder scan:

- The plan does not use placeholder markers or unspecified “add tests” steps.
- Each implementation task includes concrete code snippets and exact commands.

Type consistency:

- `MemoryGateway.retrieve` and `MemoryGateway.apply` use `MemoryScope`.
- `SpeechGateway.speak` uses `SpeechPace`.
- `TurnResult.context_decision`, `reasoning_response`, `memory_operation`, and `errors` names are consistent across tests and implementation snippets.
- `ConciergeOrchestrator.handle_transcript` is the single public orchestration entry point used by every test.
