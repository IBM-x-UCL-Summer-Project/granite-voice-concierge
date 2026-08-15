"""Construction helpers for persistent local memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from voice_concierge.local_storage import MEMORY_DATABASE_PATH, VECTOR_DATABASE_PATH
from voice_concierge.memory.decay import MemoryDecayPolicy

if TYPE_CHECKING:
    from voice_concierge.memory.embedding_service import EmbeddingService
    from voice_concierge.memory.memory_manager import MemoryManager
    from voice_concierge.memory.memory_validator import MemoryValidator

DEFAULT_MEMORY_DB_PATH = MEMORY_DATABASE_PATH
DEFAULT_VECTOR_DB_PATH = VECTOR_DATABASE_PATH
DEFAULT_EMBEDDING_MODEL = "granite-embedding:278m"
DEFAULT_EMBEDDING_DIMENSION = 768


@dataclass(frozen=True)
class LocalMemoryConfig:
    """Filesystem and embedding configuration for local persistent memory."""

    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH
    vector_db_path: str | Path = DEFAULT_VECTOR_DB_PATH
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    decay_policy: MemoryDecayPolicy = field(default_factory=MemoryDecayPolicy)


def build_memory_manager(
    config: LocalMemoryConfig | None = None,
    *,
    embedding_service: EmbeddingService | None = None,
    validator: MemoryValidator | None = None,
) -> MemoryManager:
    """Build local SQLite memory storage and semantic retrieval components."""

    from voice_concierge.memory.embedding_service import EmbeddingService
    from voice_concierge.memory.memory_manager import MemoryManager
    from voice_concierge.memory.memory_store import MemoryStore
    from voice_concierge.memory.vector_store import VectorStore

    runtime_config = config or LocalMemoryConfig()
    memory_db_path = Path(runtime_config.memory_db_path)
    vector_db_path = Path(runtime_config.vector_db_path)
    memory_db_path.parent.mkdir(parents=True, exist_ok=True)
    vector_db_path.parent.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(memory_db_path)
    try:
        vector_store = VectorStore(
            vector_db_path,
            dimension=runtime_config.embedding_dimension,
        )
    except Exception:
        memory_store.close()
        raise

    embeddings = embedding_service or EmbeddingService(
        model_name=runtime_config.embedding_model
    )
    manager = MemoryManager(
        memory_store=memory_store,
        vector_store=vector_store,
        embedding_service=embeddings,
        validator=validator,
        decay_policy=runtime_config.decay_policy,
    )
    manager.migrate_legacy_structured_lists()
    manager.reconcile_index()
    return manager
