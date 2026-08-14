"""Assemble a privacy centre over the real local memory system."""

# Standard library
from pathlib import Path

# Local
from voice_concierge.privacy.centre import PrivacyCentre


def build_privacy_centre(memory_manager: object | None = None) -> PrivacyCentre:
    """Build a PrivacyCentre over the local memory manager.

    The manager is built here when not supplied, so a caller reviewing their
    data does not have to know how the memory system is wired together.
    """
    if memory_manager is None:  # pragma: no cover - opens the real databases
        from voice_concierge.memory import build_memory_manager

        memory_manager = build_memory_manager()
    return PrivacyCentre(memory_manager)  # type: ignore[arg-type]


def default_database_paths() -> tuple[Path, Path]:
    """Return the memory and vector database paths the assistant uses."""
    from voice_concierge.memory import DEFAULT_MEMORY_DB_PATH, DEFAULT_VECTOR_DB_PATH

    return Path(DEFAULT_MEMORY_DB_PATH), Path(DEFAULT_VECTOR_DB_PATH)
