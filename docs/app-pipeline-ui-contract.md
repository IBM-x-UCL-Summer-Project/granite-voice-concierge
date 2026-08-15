# App Pipeline UI Contract

Status: implemented Python app-pipeline contract for frontend/backend planning.
The browser UI should connect through a backend wrapper rather than importing
the Python package directly.

The app pipeline is turn-based and stateful. Trusted in-process callers may pass
the `state` returned from one turn into the next. A network backend must keep the
authoritative state server-side and associate it with the local client; browser
state is display data, not authority for confirmations or memory mutations.

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

The factory also supplies the local system date and time to reasoning through a
trusted runtime provider. This is local-only and requires no service or
credential. Serialized UI requests cannot inject runtime facts.

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
    handle_audio_turn,
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
  options?: {
    synthesize?: boolean; // default false
    play?: boolean; // default false, mostly for local/manual testing
  };
};
```

The included web wrapper accepts transcripts at `POST /api/turn`. It accepts a
base64-encoded, mono 16-bit PCM WAV at `POST /api/audio` and routes it through
the pipeline's `process_audio(...)` method. It uses an HTTP-only, same-site
session cookie to select server-owned pipeline state. A posted `state` field is
ignored for backwards compatibility and cannot inject a pending action.

## Backend Adapter

The framework-free adapter accepts and returns plain dictionaries:

```py
response_payload = handle_turn(request_payload, pipeline)
audio_response_payload = handle_audio_turn(audio_request_payload, pipeline)
```

`handle_turn(...)` parses the request with `app_turn_request_from_dict(...)`,
calls `pipeline.process_request(...)`, then serializes the result with
`app_turn_result_to_dict(...)`. `handle_audio_turn(...)` decodes the browser WAV
and calls `pipeline.process_audio(...)` with the same state and options contract.
These low-level adapters accept serialized state for trusted callers and test
tools. An HTTP or other untrusted transport must substitute server-owned state
before calling them, as the included web wrapper does.

Malformed payloads raise `PayloadValidationError`. The included HTTP wrapper
translates that exception into a 400 response.

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

The response includes this whole object so the UI can render conversation and
confirmation state. The included browser stores it as a local display cache but
does not send it back. The server retains the authoritative copy used for the
next turn. A frontend must never create or edit pending actions or targets.

`conversation_history` contains short-term session context only. The pipeline
keeps at most six completed exchanges and passes prior exchanges to reasoning so
follow-up references can be understood. It is separate from approved persistent
memory. A client may render its response copy, but the server-owned value is the
only one used for reasoning.

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
    content: string | null;
    rationale: string;
    target?: {
      memory_id?: number;
      memory_key?: string;
      expected_revision?: number;
    };
    list_operation?: {
      list_name: 'shopping' | 'task';
      operation: 'add_items';
      items: string[];
    };
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

Every pending `update` or `delete` includes an exact target. `memory_id`
identifies a retrieved record, `memory_key` identifies an explicitly scoped
singleton such as `list:shopping`, and `expected_revision` prevents a stale
confirmation from overwriting a newer value. A `store` may include only a
`memory_key` when it is creating the first value for that scoped record. These
fields stay within server-owned state; the UI must not choose a target from
memory content.

Shopping-list and task-list writes use `list_operation`; their `content` is
`null`. The typed item array is the only mutation payload for those actions.
The memory domain creates canonical persisted content for a first item and
applies later additions itself. Command strings embedded in `content` are not
part of the contract.

When a memory action is pending, the next transcript is interpreted as a
confirmation reply. Only a complete, explicit answer such as `yes`, `confirm`,
`no`, or `cancel` resolves it. An ambiguous reply leaves both pending fields
unchanged and asks the user for an explicit yes or no; it must never apply or
discard the action based on a word embedded in unrelated speech.

## Response Shape

The Python `AppTurnResult.response_audio` field is a `CapturedAudio | None`.
A web backend wrapper should convert it to a browser-friendly representation
such as the optional `audio` object shown below.

```ts
type MemoryOperationStatus =
  | 'stored_successfully'
  | 'stored_pending_index'
  | 'duplicate_key'
  | 'duplicate_found'
  | 'validation_failed'
  | 'storage_error'
  | 'updated_successfully'
  | 'updated_pending_index'
  | 'memory_not_found'
  | 'memory_revision_conflict'
  | 'no_changes'
  | 'update_error'
  | 'deleted_successfully'
  | 'deleted_pending_index_cleanup'
  | 'delete_error'
  | 'memory_action_error'
  | 'memory_target_not_found'
  | 'memory_target_mismatch'
  | 'structured_list_target_mismatch'
  | 'invalid_structured_list_content'
  | 'unknown_action'
  | 'memory_not_configured'
  | 'memory_scope_none'
  | 'structured_list_scope_mismatch'
  | 'memory_scope_mismatch'
  | 'memory_gateway_error';

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
    information_evidence: Array<
      | {
          source: 'user_input';
          quote: string;
        }
      | {
          source: 'memory';
          quote: string;
          memory_id: number;
          memory_revision: number;
        }
      | {
          source: 'conversation_summary';
          quote: string;
        }
      | {
          source: 'runtime_context';
          quote: string;
          runtime_id: string;
          observed_at: number;
        }
    >;
    freshness_requirement: 'not_required' | 'current';
    needs_confirmation: boolean;
    proposed_memory_action: AppPipelineState['pending_memory_action'];
    mode_suggestion: string | null;
  } | null;

  memory_operation: {
    attempted: boolean;
    succeeded: boolean;
    status: MemoryOperationStatus | null;
    memory_id: number | null;
    detail: string | null;
    similarity_advisories: Array<{
      memory_id: number;
      distance: number;
    }>;
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

When `memory_operation.attempted` is true, `status` is the stable
machine-readable memory status and `succeeded` is derived from that status.
`memory_id` and `detail` carry optional structured context.
`similarity_advisories` reports semantically close existing records from the
same metadata scope after a successful store; it is evidence only and never a
write rejection. `reason` is retained as a display/logging string; clients
should not parse it to make decisions.

The app memory gateway translates reasoning proposals into memory-owned
commands only after checking their typed target and the active safety policy.
Personal retrieval is restricted to profile records, task retrieval to
feedback/task records, and shopping retrieval to the stable shopping-list
record. Explicit shopping-list and task-list queries route to those stable
records even when the UI is in another non-driving mode. Structured mutations
derive their scope from their stable list target rather than the current UI
mode; an untyped store is personal. Driving mode still disables memory access.
An update or delete whose exact target falls outside its resolved scope returns
`memory_scope_mismatch` without reaching persistence.

## Error Codes

Expected recoverable errors:

```ts
type AppTurnError =
  | 'empty_transcript'
  | 'stt_failed'
  | 'memory_retrieval_failed'
  | 'runtime_context_failed'
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
    "status": null,
    "memory_id": null,
    "detail": null,
    "similarity_advisories": [],
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

The frontend then sends only the user's confirmation. The HTTP-only session
cookie identifies the server-owned pending state:

```json
{
  "transcript": "yes"
}
```

The backend makes one mutation attempt and returns updated state with
`pending_memory_action: null`, whether that attempt succeeds or fails. This
prevents later conversation from being trapped in a stale yes/no prompt; the
user can restate a failed request. Confirming a record that is already stored
is reported as an idempotent completion and does not surface
`memory_action_failed`.

## Frontend Rule

Display fields such as `spoken_response`, `context.mode`,
`context.needs_confirmation`, and `errors`. Keep returned `state` only as an
opaque display cache; do not send it as authority on the next HTTP turn. The UI
can maintain a separate display-message list if it needs richer rendering
metadata. Treat the returned `state.context.accessibility` as the pipeline's
current verbosity and speech pace; browser audio controls may apply device-local
volume and rate multipliers without rewriting it.
