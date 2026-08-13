# routines

Guided **routines / checklists** for the voice concierge: start a routine by
voice, then step through it hands-free ("next", "go back", "repeat", "pause",
"continue", "stop") — for cooking, shopping prep, and household tasks.

## Design

Approach B — a **voice-free core** plus a **thin voice adapter**:

- `RoutineSession` (`session.py`) — a pure state machine over a `Routine`. Every
  command returns a `RoutineResponse` (an *outcome* + optional `StepView`); it
  never raises for a normal edge case and has no opinion about English.
- `RoutineProvider` (`interfaces.py`) — supplies routines. Implementations:
  `MemoryRoutineProvider` (saved routines, `topic="routine"`),
  `LLMRoutineProvider` (reasoning engine, strict numbered-step parse),
  `StaticRoutineProvider` (the fake), and `ChainedRoutineProvider`
  (memory-first, LLM fallback). The chain also forwards `find_candidates`, so a
  memory-backed match set can drive disambiguation through the built stack.
- `RoutineCommandAdapter` (`adapter.py`) — the only place English lives. Maps a
  `command_control` `CommandEvent` onto session calls, owns ask-then-default
  disambiguation, and degrades a backend failure to a generic spoken line.

- `RoutineRunner` (`runner.py`) — decides *when* the next command happens.
  Reads a step, allows a short window to steer, and auto-advances on silence; a
  paused routine waits instead. Audio sits behind the `StepSpeaker` and
  `CommandWaiter` protocols, so the whole policy is tested with fakes.
- `is_routine_request` (`intent.py`) — the gate deciding which turns become
  routines. An explicit phrase list, not a model call: `LLMRoutineProvider` will
  produce steps for *any* request, so routing every turn through it would take
  over the assistant.

Ownership: `command_control` = *hear a command*; `routines` = *what a routine
means and when it moves*; `app/` = *wire them to real audio*.

## In the app

`app/routines.py` supplies the two audio-facing pieces and is what
`voice_concierge.app.live` builds: `EchoCancelledStepSpeaker` (speaks a step
through the echo-cancelled player with the mic live, so a command can barge in)
and `MicCommandWaiter` (listens in the quiet gap between steps, where a plain
input stream is safe). `RoutineTurnHandler` joins the gate to the runner. The
stack is built lazily on the first guided request, so a user who never asks for
one never loads the recognizer or the reasoning backend.

## Usage

```python
from voice_concierge.routines import build_routine_adapter

adapter = build_routine_adapter(memory_manager=memory, reasoning_engine=engine)

print(adapter.start_routine("make a cup of tea"))   # -> "Step 1 of 3. Boil water."
# then, from the barge-in / wake-word command stream:
print(adapter.handle_command(next_event))           # -> "Step 2 of 3. ..."
```

When more than one saved routine matches, `start_routine` asks the user to
choose; a follow-up reply is resolved with `adapter.resolve_choice(reply)`,
defaulting to the most recent if the reply does not name one.

## Scope

- **Implemented:** following a routine (start + next/back/repeat/pause/resume/stop),
  memory + LLM step sources, ask-then-default disambiguation (including through
  the provider chain).
- **Deferred:** creating/editing routines by voice; timers inside a step (issue #42);
  a GUI.


## Changing the speaking pace

Saying **"slower"** or **"faster"** while a step is being read changes the
speaking rate and reads the step again at the new speed. The audio for a step is
rendered before playback starts, so its speed cannot be altered mid-sentence;
re-reading is both the only way to apply the new rate and what someone asking to
hear it slower actually wants.

The rate moves along a fixed ladder (`voice_output/pacing.py`) rather than
scaling freely, so each step is noticeable but not jarring and the voice can
never become unintelligible. At either end the assistant says so ("That's as
slow as I can go") rather than staying silent, which would read as the command
not having been heard.

The chosen pace is remembered at `.local/preferences/speech-pace.json` and
restored next time, so someone who has asked the assistant to slow down does not
have to ask again every session. Pass `persist=False` to
`build_paced_text_to_speech` to keep a session's pace to itself. Saving is best
effort: an unwritable preferences file costs the memory of the setting, never
the ability to change it now.
