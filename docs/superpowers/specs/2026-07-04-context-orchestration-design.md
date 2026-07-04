# Context Orchestration Design

## Goal

Connect context decisions to memory retrieval, local reasoning, and speech output
through a testable orchestration layer. The integration must run in unit tests
without Ollama, model files, a microphone, speakers, or a live database.

## Scope

This change introduces a text-level `ConciergeOrchestrator`. A voice/STT caller
hands it a completed transcript; audio capture and transcription remain outside
the orchestrator. The orchestrator coordinates one user turn, owns the
cross-turn state needed for that coordination, and returns a structured result.

The change includes:

- a public context confirmation-intent classifier shared by mode and memory
  confirmation flows;
- a new orchestration package with dependency protocols, turn result types,
  concrete adapters, and `ConciergeOrchestrator`;
- minimal backward-compatible adaptations to memory and speech output where
  the existing public APIs do not expose the required behavior;
- unit and integration-style tests using deterministic fakes.

The change does not include:

- microphone or wake-word runtime wiring;
- converting captured NumPy audio into an STT-compatible input;
- installing or downloading models;
- changing the reasoning prompt format;
- durable persistence of orchestration session state across process restarts.

## Chosen Architecture

`ContextManager` remains a pure decision component. It does not import memory,
reasoning, or speech implementations. A separate orchestration package owns
composition:

```text
Voice/STT callback
       |
       | transcript
       v
ConciergeOrchestrator
       |-- ContextManager
       |-- MemoryGateway
       |-- ReasoningEngine
       `-- SpeechGateway
```

All collaborators are injected. Reasoning uses the existing
`ReasoningEngine` protocol. The orchestration package defines small protocols
for memory and speech because their current concrete APIs are not shaped around
a single assistant turn. Production adapters wrap `MemoryManager` and
`OfflineTTS`; tests provide in-memory fakes.

This avoids importing model, database, and audio dependencies when only the
orchestration types or test fakes are used.

## Components

### Context confirmation intent

The context package exposes:

```python
ConfirmationIntent = Literal["confirm", "cancel"]

def detect_confirmation_intent(transcript: str) -> ConfirmationIntent | None:
    ...
```

`ContextManager` uses this function for a pending mode. The orchestrator uses
the same function for a pending memory action. Existing accepted phrases remain
compatible.

### Orchestration ports

`MemoryGateway` exposes:

```python
def retrieve(
    query: str,
    scope: MemoryScope,
    limit: int = 3,
) -> tuple[str, ...]:
    ...

def apply(
    action: MemoryAction,
    scope: MemoryScope,
) -> tuple[bool, str]:
    ...
```

`SpeechGateway` exposes:

```python
def speak(self, text: str, pace: SpeechPace) -> bool:
    ...

def stop(self) -> bool:
    ...
```

The concrete memory adapter maps context scope as follows:

- `none`: do not call `MemoryManager`;
- `personal_relevant`: semantic retrieval without a topic filter;
- `task_relevant_only`: semantic retrieval with topic `procedural`;
- `list_relevant`: semantic retrieval with topic `shopping`.

The adapter delegates confirmed memory actions to `MemoryManager`. For a
shopping-mode store action, it stores the content with topic `shopping`;
otherwise it uses the existing `process_memory_action` behavior. This keeps
shopping-list retrieval internally consistent without changing the reasoning
response contract.

The concrete speech adapter maps `normal` pace to Piper length scale `1.2` and
`slow` pace to `1.5`. Its `stop` operation calls the speech output stop API.

### Turn result

`TurnResult` is an immutable dataclass containing:

- the latest `ContextDecision`;
- the text selected for speech;
- the `ReasoningResponse`, when reasoning ran;
- whether speech succeeded;
- whether a memory operation was attempted and its result;
- stable error codes collected during recoverable failures.

This result is the observable contract for tests and a future UI. Callers never
need to inspect orchestrator internals.

### ConciergeOrchestrator state

The orchestrator keeps:

- the current `ContextState`;
- the last selected spoken response for `repeat`;
- one pending `MemoryAction` and the `MemoryScope` under which it was proposed.

This state is session-local. Constructor arguments may provide an initial
`ContextState`; no disk persistence is introduced.

## Turn Data Flow

For `handle_transcript(transcript)`:

1. Normalize only enough to detect an empty transcript. Context remains the
   owner of command and confirmation phrase normalization.
2. An empty transcript selects a fixed “I didn't catch that” response and does
   not call memory or reasoning.
3. If a memory action is pending:
   - explicit confirmation applies it through `MemoryGateway`;
   - explicit cancellation discards it;
   - any other transcript implicitly cancels it and continues as a new turn.
4. Call `ContextManager.handle(transcript, current_state)` and store the
   returned state.
5. If a mode change needs confirmation, select the context confirmation prompt
   and skip memory and reasoning.
6. Handle deterministic commands:
   - `repeat` selects the previous spoken response and skips memory/reasoning;
   - `stop` invokes `SpeechGateway.stop`, skips memory/reasoning, and returns a
     fixed acknowledgement;
   - `cancel` returns a fixed acknowledgement when context has not already
     supplied a mode-cancellation outcome;
   - `next_step` continues to reasoning so the current mode and transcript
     shape the next instruction.
7. Retrieve memory with the active policy's `memory_scope`. The `none` scope
   performs no retrieval.
8. Build `ReasoningRequest` with:
   - `mode=policy.mode`;
   - the retrieved memory tuple;
   - `constraints.max_words=policy.max_words`;
   - `constraints.allow_memory_writes=(policy.memory_scope != "none")`;
   - the original transcript.
9. Generate a `ReasoningResponse`.
10. If the response proposes a memory action that requires confirmation, retain
    it as pending. Do not execute it in the same turn.
11. Select `spoken_response`, save it as the repeatable response, and call
    `SpeechGateway.speak` with `policy.speech_pace`.
12. Return `TurnResult`.

The reasoning response's `mode_suggestion` remains advisory. It is exposed in
`TurnResult` through the full reasoning response, but it does not automatically
change context mode. An automatic switch would bypass the context package's
explicit user confirmation rule.

## Error Handling

Expected dependency failures are isolated at the orchestration boundary:

- Memory retrieval failure records `memory_retrieval_failed`, continues with
  an empty memory tuple, and still calls reasoning.
- Reasoning failure records `reasoning_failed`, selects a short fixed fallback,
  and still attempts speech.
- Speech returning `False` or raising records `speech_failed`; generated text
  remains available in `TurnResult`.
- Memory action failure records `memory_action_failed`. The pending action is
  retained so the caller may retry or cancel it on the next turn.
- Empty input records `empty_transcript` and returns the fixed clarification
  response.

Programming errors are not silently swallowed. The orchestrator catches
exceptions only around injected dependency calls and reports stable public
error codes rather than exception text.

## Testing Strategy

Development follows red-green-refactor. Tests use fake gateways and the
existing deterministic reasoning fake.

Required behavior tests:

- home mode retrieves personal memory and forwards mode, memories, and a
  60-word limit to reasoning;
- cooking mode forwards `task_relevant_only`, a 55-word limit, and allows
  `next_step` to reach reasoning;
- shopping mode forwards `list_relevant` and confirmed store operations use
  shopping scope;
- driving mode requires confirmation, then skips memory, uses a 25-word limit,
  and disables memory writes;
- accessibility phrases update the speech pace and word limit passed
  downstream;
- `repeat` reuses the previous selected response without memory or reasoning;
- `stop` calls the speech stop port without memory or reasoning;
- proposed memory actions are not applied before confirmation;
- memory confirmation, cancellation, implicit cancellation, failure retention,
  and retry behave as specified;
- empty transcripts and memory, reasoning, and speech failures produce their
  specified recoverable results.

Adapter tests verify scope-to-filter mapping and speech pace-to-length-scale
mapping without loading concrete models. Existing context, memory, reasoning,
and voice-input tests remain part of the final regression run.

## Compatibility

Existing imports and method signatures remain valid. New public APIs are
exported from their package `__init__.py` files. Any optional parameters added
to concrete memory or speech methods have defaults preserving current behavior.

No production module instantiates Ollama, database, or audio dependencies at
import time solely because the orchestration package is imported.

## Success Criteria

The work is complete when:

- `ConciergeOrchestrator` coordinates context, memory, reasoning, and speech
  through injected interfaces;
- all four context policies affect downstream requests as specified;
- confirmation and deterministic command paths bypass unnecessary dependencies;
- recoverable dependency failures return structured results;
- the orchestration suite and the full existing test suite pass;
- Ruff and formatting checks pass for changed Python files.
