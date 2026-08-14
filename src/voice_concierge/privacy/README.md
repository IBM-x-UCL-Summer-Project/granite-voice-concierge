# privacy

The **memory and privacy centre**: a user-facing way to see what the assistant
has stored about you, correct it, remove it, or take a copy.

Local processing is not the same as user control. The assistant already keeps
everything on the device, but until now nothing let the person it is about read
what had been remembered, fix a memory that was wrong, or erase it. This package
closes that gap.

## Design

The same split used elsewhere in the codebase: a pure core plus a thin surface.

- `PrivacyCentre` (`centre.py`) - all the rules. Lists, filters, corrects,
  deletes and exports. Does no printing and opens no database. It reads through
  the narrow `MemoryArchive` protocol, which exposes only read, update and
  delete, so this package cannot write new memories or run retrieval.
- `disclosure.py` - explains what is stored. The report is built from the
  authoritative local-storage catalogue and the real files on disk (path,
  existence, size), rather than from a second list that can drift away from the
  code. It also states what is deliberately *not* kept.
- `cli.py` - renders, prompts and confirms. No policy lives here, so a voice or
  web front end can reuse the core unchanged.

## Two rules the core keeps

**Never report success that did not happen.** Every failure raises
`PrivacyError` rather than returning quietly, and `delete_all` reports how many
memories it removed before stopping. A privacy control that silently fails is
worse than one that refuses.

**Deleting a memory deletes its embedding.** Removal goes through the memory
manager, which clears the vector store too, so erased content does not survive
in the search index.

## Usage

```bash
python -m voice_concierge.privacy              # what is stored, and what is not
python -m voice_concierge.privacy list -v      # review, with dates and sources
python -m voice_concierge.privacy list --search tea
python -m voice_concierge.privacy export       # take a copy as JSON
python -m voice_concierge.privacy edit 3 "likes tea, not coffee"
python -m voice_concierge.privacy delete 3     # asks first
python -m voice_concierge.privacy forget-all   # asks you to type DELETE
```

Deleting one memory shows it before asking. Erasing everything requires typing
`DELETE` in full, because it cannot be undone and a stray keypress should not be
enough. `-y` skips the prompt for scripted use.

```python
from voice_concierge.privacy import build_privacy_centre

centre = build_privacy_centre()
for memory in centre.list_memories(search="tea"):
    print(memory.identifier, memory.content, memory.layer_description)
```

## What is stored, and what is not

Stored on disk:

| What | Where |
| --- | --- |
| Memories, as readable text | `.local/memory/memories.sqlite3` |
| Their search index (embeddings) | `.local/memory/vectors.sqlite3` |
| Reminders and timers | `.local/reminders/reminders.sqlite3` |
| Speaking pace preference | `.local/preferences/speech-pace.json` |
| Selected local reasoning model | `.local/reasoning-model-selection.json` |

Not stored: recorded audio (transcribed then discarded), conversation history
(held in process memory only, lost on exit), transient context and accessibility
modes, and anything off-device, since all processing including the language
model runs locally.

That last group matters as much as the first. The issue behind this package
asked for control over "memories, conversation history and preferences". The
report therefore distinguishes persisted memories and preferences from settings
that only exist for the current session.

## Memory layers

Every layer the system writes is explained in plain English
(`LAYER_DESCRIPTIONS`): `episodic`, `semantic`, `procedural`, `emotional`,
`reflective` from the memory validator, and `profile` from the app layer. An
unrecognised layer is shown by name rather than hidden, so nothing stored is
left undisclosed.
