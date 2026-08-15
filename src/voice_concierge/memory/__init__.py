"""Local memory management system for voice concierge.

Persistent database dependencies stay lazy so the app pipeline can run with its
default no-op memory gateway in lightweight or UI-only installations.
"""

from __future__ import annotations

from typing import Any

from voice_concierge.memory.factory import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MEMORY_DB_PATH,
    DEFAULT_VECTOR_DB_PATH,
    LocalMemoryConfig,
)
from voice_concierge.memory.types import (
    ApplyStructuredListCommand,
    DeleteMemoryCommand,
    ExtractedMemoryMetadata,
    MemoryCommand,
    MemoryCommandTarget,
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
    MemoryRecordScope,
    MemorySearchResult,
    MemorySimilarityAdvisory,
    MemoryUpdate,
    MemoryWrite,
    StoreMemoryCommand,
    StructuredListMutation,
    UpdateMemoryCommand,
    VectorSearchResult,
    normalize_event_time,
    normalize_memory_strength,
)

__all__ = [
    "ApplyStructuredListCommand",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_MEMORY_DB_PATH",
    "DEFAULT_VECTOR_DB_PATH",
    "DeleteMemoryCommand",
    "EmbeddingService",
    "ExtractedMemoryMetadata",
    "IndexReconciliationResult",
    "LocalMemoryConfig",
    "MemoryManager",
    "MemoryCommand",
    "MemoryCommandTarget",
    "MemoryDecayPolicy",
    "MemoryOperationOutcome",
    "MemoryOperationStatus",
    "MemoryRecord",
    "MemoryRetriever",
    "MemoryRecordScope",
    "MemorySearchResult",
    "MemorySimilarityAdvisory",
    "MemoryStore",
    "MemoryUpdate",
    "MemoryValidator",
    "MemoryWrite",
    "StoreMemoryCommand",
    "StructuredListMutation",
    "UpdateMemoryCommand",
    "VectorStore",
    "VectorSearchResult",
    "build_memory_manager",
    "normalize_event_time",
    "normalize_memory_strength",
]


def __getattr__(name: str) -> Any:
    modules = {
        "EmbeddingService": ("voice_concierge.memory.embedding_service", name),
        "IndexReconciliationResult": (
            "voice_concierge.memory.memory_manager",
            name,
        ),
        "MemoryDecayPolicy": ("voice_concierge.memory.decay", name),
        "MemoryManager": ("voice_concierge.memory.memory_manager", name),
        "MemoryRetriever": ("voice_concierge.memory.memory_retriever", name),
        "MemoryStore": ("voice_concierge.memory.memory_store", name),
        "MemoryValidator": ("voice_concierge.memory.memory_validator", name),
        "VectorStore": ("voice_concierge.memory.vector_store", name),
        "build_memory_manager": ("voice_concierge.memory.factory", name),
    }
    target = modules.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
