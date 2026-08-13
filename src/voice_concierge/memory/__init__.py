"""Local memory management system for voice concierge."""

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.factory import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MEMORY_DB_PATH,
    DEFAULT_VECTOR_DB_PATH,
    LocalMemoryConfig,
    build_memory_manager,
)
from voice_concierge.memory.memory_manager import (
    IndexReconciliationResult,
    MemoryManager,
)
from voice_concierge.memory.memory_retriever import MemoryRetriever
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.memory_validator import MemoryValidator
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
from voice_concierge.memory.vector_store import VectorStore

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
