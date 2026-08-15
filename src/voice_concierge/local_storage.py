"""Authoritative catalogue of project-owned persistent local state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalStorageFile:
    """One file the assistant deliberately persists on the local device."""

    key: str
    name: str
    path: Path
    description: str


MEMORY_DATABASE_PATH = Path(".local/memory/memories.sqlite3")
VECTOR_DATABASE_PATH = Path(".local/memory/vectors.sqlite3")
REMINDER_DATABASE_PATH = Path(".local/reminders/reminders.sqlite3")
SPEECH_PACE_PATH = Path(".local/preferences/speech-pace.json")
REASONING_MODEL_SELECTION_PATH = Path(".local/reasoning-model-selection.json")


LOCAL_STORAGE_FILES: tuple[LocalStorageFile, ...] = (
    LocalStorageFile(
        key="memories",
        name="Memories",
        path=MEMORY_DATABASE_PATH,
        description="The things the assistant has remembered, as readable text.",
    ),
    LocalStorageFile(
        key="memory-search-index",
        name="Memory search index",
        path=VECTOR_DATABASE_PATH,
        description=(
            "Numerical representations of memories, used only for local search."
        ),
    ),
    LocalStorageFile(
        key="reminders",
        name="Reminders and timers",
        path=REMINDER_DATABASE_PATH,
        description=("Reminder text, due times, recurrence rules, and delivery state."),
    ),
    LocalStorageFile(
        key="speech-pace",
        name="Speaking pace preference",
        path=SPEECH_PACE_PATH,
        description="The locally selected speaking-pace level.",
    ),
    LocalStorageFile(
        key="reasoning-model-selection",
        name="Reasoning model selection",
        path=REASONING_MODEL_SELECTION_PATH,
        description="The local reasoning backend and model selected by the user.",
    ),
)
