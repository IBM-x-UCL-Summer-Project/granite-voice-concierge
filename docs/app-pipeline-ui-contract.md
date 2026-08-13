# App Pipeline UI Contract

Status: implemented Python app-pipeline contract for frontend/backend planning.
The browser UI should connect through a backend wrapper rather than importing
the Python package directly.

The app pipeline is turn-based and stateful. A UI or backend wrapper should send
one user turn at a time, along with the `state` returned from the previous turn.
The pipeline returns the assistant response and the next state.

The frontend should not need to know about STT, TTS, Ollama, memory internals, or
context-manager internals.

## Local Persistent Memory

Persistent memory is opt-in when constructing the pipeline so unit tests and
installations without the embedding model remain lightweight:

```py
from voice_concierge.app import build_voice_concierge_pipeline
from voice_concierge.memory import LocalMemoryConfig

pipeline = build_voice_concierge_pipeline(
    memory_config=LocalMemoryConfig(),
    load_memory=True,
)

try:
    result = pipeline.process_transcript("remember that I prefer tea")
finally:
    pipeline.close()
```

The default configuration stores SQLite data under `.local/memory/`, which is
ignored by Git. Semantic retrieval uses the local Ollama
`granite-embedding:278m` model. Install it before enabling memory:

```bash
ollama pull granite-embedding:278m
```

Confirmed writes are stored without a second model-based classification step.
The app context policy supplies the storage layer and topic, while the embedding
model supplies only the vector used for later retrieval.

## Request Shape

Python entry points:

```py
from voice_concierge.app import (
    app_pipeline_state_from_dict,
    app_pipeline_state_to_dict,
    app_turn_request_from_dict,
    app_turn_result_to_dict,
    handle_turn,
)

pipeline.process_transcript(
    transcript: str,
    state: AppPipelineState | None = None,
    *,
    synthesize: bool = False,
    play: bool = False,
) -> AppTurnResult

pipeline.process_audio(
    audio: CapturedAudio,
    state: AppPipelineState | None = None,
    *,
    synthesize: bool = False,
    play: bool = False,
) -> AppTurnResult
```

Equivalent frontend-facing request shape:

```ts
type AppTurnRequest = {
  transcript: string;
  state?: AppPipelineState | null;
  options?: {
    synthesize?: boolean; // default false
    play?: boolean; // default false, mostly for local/manual testing
  };
};
```

For the web UI, use `transcript`. Audio input can be added later by a backend
wrapper using the pipeline's `process_audio(...)` method.

## Backend Adapter

The framework-free adapter accepts and returns plain dictionaries:

```py
response_payload = handle_turn(request_payload, pipeline)
```

`handle_turn(...)` parses the request with `app_turn_request_from_dict(...)`,
calls `pipeline.process_request(...)`, then serializes the result with
`app_turn_result_to_dict(...)`.

Malformed payloads raise `PayloadValidationError`. An HTTP wrapper should
translate that exception into a 400 response.

## Fake Smoke Runner

For local transcript-only checks without Ollama, STT, TTS, audio devices, or
persistent memory, run:

```bash
python -m voice_concierge.app.smoke "remember that I prefer tea" "yes" "what do you remember"
```

The command prints JSON containing each request payload and response payload. It
uses deterministic fake reasoning plus in-memory fake memory, and it round-trips
state through the same `handle_turn(...)` adapter a backend wrapper would call.

Checked-in example request/response payloads live in
`docs/app-pipeline/examples/` and are covered by tests so they stay aligned with
the adapter output.

## State Shape

The UI should store this whole object and send it back on the next turn. Treat it
as application state owned by the pipeline, not as frontend business logic.

`conversation_history` contains short-term session context only. The pipeline
keeps at most six completed exchanges and passes prior exchanges to reasoning so
follow-up references can be understood. It is separate from approved persistent
memory and should not be edited by the UI.

```ts
type AppPipelineState = {
  context: {
    mode: 'home' | 'cooking' | 'shopping' | 'driving';
    pending_mode: 'home' | 'cooking' | 'shopping' | 'driving' | null;
    last_topic: string | null;
    accessibility: {
      verbosity: 'short' | 'normal';
      speech_pace: 'slow' | 'normal';
    };
  };

  last_spoken_response: string | null;

  conversation_history: Array<{
    user_transcript: string;
    assistant_response: string;
  }>;

  pending_memory_action: null | {
    action: 'store' | 'delete' | 'update';
    content: string;
    rationale: string;
    target_key?: string | null;
    requires_confirmation: boolean;
  };

  pending_memory_scope:
    | 'none'
    | 'personal_relevant'
    | 'task_relevant_only'
    | 'list_relevant'
    | null;
};
```

## Response Shape

The Python `AppTurnResult.response_audio` field is a `CapturedAudio | None`.
A web backend wrapper should convert it to a browser-friendly representation
such as the optional `audio` object shown below.

```ts
type AppTurnResponse = {
  state: AppPipelineState;

  transcript: {
    text: string;
    language?: string | null;
    language_probability?: number | null;
  } | null;

  spoken_response: string;

  context: {
    mode: 'home' | 'cooking' | 'shopping' | 'driving';
    mode_changed: boolean;
    needs_confirmation: boolean;
    command_action: 'repeat' | 'next_step' | 'stop' | 'cancel' | null;
    confirmation_prompt: string;
  };

  reasoning: {
    confidence: 'low' | 'medium' | 'high';
    required_information_source:
      | 'none'
      | 'user_input'
      | 'local_context'
      | 'stable_knowledge'
      | 'runtime_live'
      | 'external_live';
    freshness_requirement: 'not_required' | 'current';
    needs_confirmation: boolean;
    proposed_memory_action: AppPipelineState['pending_memory_action'];
    mode_suggestion: string | null;
  } | null;

  memory_operation: {
    attempted: boolean;
    succeeded: boolean;
    reason: string;
  };

  errors: AppTurnError[];

  audio?: {
    wav_base64?: string;
    sample_rate?: number;
    duration_seconds?: number;
  } | null;
};
```

## Error Codes

Expected recoverable errors:

```ts
type AppTurnError =
  | 'empty_transcript'
  | 'stt_failed'
  | 'memory_retrieval_failed'
  | 'reasoning_failed'
  | 'memory_action_failed'
  | 'tts_failed'
  | 'playback_failed';
```

The UI should still display `spoken_response` when `errors` is not empty.

## Deterministic Mode Changes

Mode transitions are application actions rather than model-generated claims.
When `context.mode_changed` is `true`, the pipeline returns a fixed activation
response and `reasoning` is `null`. Driving mode still returns its confirmation
prompt first; the deterministic activation response is returned only after the
user confirms.

The UI should treat `state.context.mode` as authoritative. It should never infer
the active mode from `spoken_response`.

## Example: Context Confirmation

Request:

```json
{
  "transcript": "Switch to driving mode",
  "state": null
}
```

Response:

```json
{
  "spoken_response": "Driving mode uses very short, safety-aware responses. Please confirm before I switch.",
  "context": {
    "mode": "home",
    "mode_changed": false,
    "needs_confirmation": true,
    "command_action": null,
    "confirmation_prompt": "Driving mode uses very short, safety-aware responses. Please confirm before I switch."
  },
  "reasoning": null,
  "memory_operation": {
    "attempted": false,
    "succeeded": false,
    "reason": ""
  },
  "errors": [],
  "state": {
    "context": {
      "mode": "home",
      "pending_mode": "driving",
      "last_topic": null,
      "accessibility": {
        "verbosity": "normal",
        "speech_pace": "normal"
      }
    },
    "last_spoken_response": "Driving mode uses very short, safety-aware responses. Please confirm before I switch.",
    "conversation_history": [
      {
        "user_transcript": "Switch to driving mode",
        "assistant_response": "Driving mode uses very short, safety-aware responses. Please confirm before I switch."
      }
    ],
    "pending_memory_action": null,
    "pending_memory_scope": null
  }
}
```

## Example: Memory Confirmation

If the assistant response includes:

```json
{
  "spoken_response": "I can remember that. Please confirm before I save it.",
  "state": {
    "conversation_history": [
      {
        "user_transcript": "Remember that I prefer short answers.",
        "assistant_response": "I can remember that. Please confirm before I save it."
      }
    ],
    "pending_memory_action": {
      "action": "store",
      "content": "User prefers short answers.",
      "rationale": "User asked the assistant to remember this preference.",
      "requires_confirmation": true
    },
    "pending_memory_scope": "personal_relevant"
  }
}
```

Then the frontend sends the full previous `state` back with the user's
confirmation:

```json
{
  "transcript": "yes",
  "state": {
    "...": "previous state object"
  }
}
```

The backend applies the pending memory action and returns updated state with
`pending_memory_action: null`.

## Frontend Rule

Display fields such as `spoken_response`, `context.mode`,
`context.needs_confirmation`, and `errors`. Always send the full returned `state`
back on the next turn. Store `conversation_history` as opaque pipeline state;
the UI can maintain a separate display-message list if it needs richer rendering
metadata.
