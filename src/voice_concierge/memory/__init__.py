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
from voice_concierge.memory.vector_store import VectorStore

__all__ = [
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_MEMORY_DB_PATH",
    "DEFAULT_VECTOR_DB_PATH",
    "EmbeddingService",
    "IndexReconciliationResult",
    "LocalMemoryConfig",
    "MemoryManager",
    "MemoryRetriever",
    "MemoryStore",
    "MemoryValidator",
    "VectorStore",
    "build_memory_manager",
]
