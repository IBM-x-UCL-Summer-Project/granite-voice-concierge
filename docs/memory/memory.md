# Memory Module API Reference

Complete API documentation for the memory module.

---

## Local Construction

Use the memory factory for application code instead of constructing each
storage component directly:

```python
from voice_concierge.memory import LocalMemoryConfig, build_memory_manager

manager = build_memory_manager(LocalMemoryConfig())
```

The defaults create:

- `.local/memory/memories.sqlite3` for memory records;
- `.local/memory/vectors.sqlite3` for sqlite-vec embeddings;
- 768-dimension vectors from the local Ollama
  `granite-embedding:278m` model.

`LocalMemoryConfig` can override both paths, the embedding model, and vector
dimension. Parent directories are created automatically. Call `manager.close()`
when the owner shuts down.

The SQL memory record is authoritative; sqlite-vec is a rebuildable derived
index. Each record stores both its current `revision` and `indexed_revision`.
Content changes are immediately durable in SQL and remain excluded from
semantic results until the matching vector revision is ready. Deletion first
hides the record with a tombstone, then removes its vector and purges the
tombstone. This prevents partial index failures from restoring stale SQL or
making a deleted memory visible.

`build_memory_manager()` reconciles this state during startup. Reconciliation
rebuilds stale or missing vectors, finishes tombstoned deletions, and removes
orphan vectors left by an interrupted older implementation. Semantic retrieval
also reconciles before searching. Exact stable-key reads do not require the
embedding service.

The app pipeline normally wraps this manager with `MemoryManagerGateway` by
calling `build_voice_concierge_pipeline(load_memory=True)`.

The memory package uses explicit types at its boundaries. `MemoryStore` returns
validated `MemoryRecord` instances, vector search returns
`VectorSearchResult`, and semantic retrieval returns `MemorySearchResult`
instead of adding a `distance` key to a storage dictionary. Mutations return
`MemoryOperationOutcome`; callers branch on its `MemoryOperationStatus` and
`succeeded` properties instead of positional tuple fields or parsing reason
strings. Successful stores may also carry typed `MemorySimilarityAdvisory`
values; these are evidence for a caller and never change write success. The app
gateway converts records to reasoning-owned
`MemoryReference` values. Validator/model metadata is normalized through
`ExtractedMemoryMetadata` before it can reach the SQL write boundary.

Auto-extracted ISO date text is normalized to the integer UTC timestamp used by
the SQL schema before writing. Opening a legacy database performs the same
normalization for previously stored ISO event times; invalid legacy values are
cleared rather than allowed to violate the typed record contract. Legacy
strength values are bounded to the documented 1-10 range.

Project-owned structured lists are identity-addressed records. The gateway
loads `list:shopping` and `list:tasks` by their stable keys; it never uses a
nearest semantic match as a substitute for a missing shopping list. Task mode
may add semantically relevant task context after the exact task-list record,
but semantic ranking cannot displace that record.

---

## Table of Contents

- [MemoryManager](#memorymanager) - Main interface
- [MemoryStore](#memorystore) - Storage layer
- [MemoryRetriever](#memoryretriever) - Query layer
- [MemoryValidator](#memoryvalidator) - Validation layer
- [VectorStore](#vectorstore) - Vector layer
- [EmbeddingService](#embeddingservice) - Embedding layer

---

## MemoryManager

High-level interface that integrates all components. **In most cases, you only need to use this class.**

### Initialization

```python
manager = MemoryManager(
    memory_store: MemoryStore,
    vector_store: VectorStore,
    embedding_service: EmbeddingService,
    validator: Optional[MemoryValidator] = None,
)
```

**Parameters:**

- `memory_store`: SQLite storage instance
- `vector_store`: Vector store instance
- `embedding_service`: Embedding service instance
- `validator`: Validator (optional, created by default)

### Methods

#### `store_memory()`

Store a new memory to the database and vector store.

```python
outcome = manager.store_memory(
    content: str,              # Required - Memory content
    layer: str,                # Required - profile/raw/feedback
    person: Optional[str] = None,        # Related person (auto-extracted if None)
    topic: Optional[str] = None,         # Memory type (auto-classified if None)
    source_type: Optional[str] = None,   # Source type (auto-extracted if None)
    event_time: Optional[int] = None,    # Event timestamp (auto-extracted if None)
    strength: Optional[int] = None,      # Importance 1-10 (auto-extracted if None)
    validate: bool = True,               # Whether to validate with LLM
    auto_classify: bool = True,          # Whether to auto-classify memory type
    auto_extract: bool = True,           # Whether to auto-extract metadata
    check_duplicates: bool = True,       # Exact deduplication and advisories
    memory_key: Optional[str] = None,     # Stable scoped identity when available
)
```

Duplicate enforcement is deterministic. A live `memory_key` is unique, and
unkeyed content is considered the same only after case/whitespace normalization
within the same `layer`, `person`, `source_type`, `topic`, and `event_time`.
Semantic similarity never rejects a store. The nearest qualifying result from
the same metadata scope is returned as advisory evidence after the new memory is
stored. In particular, a shopping item cannot be rejected because it resembles
a profile preference.

**Return values:**

- `MemoryOperationOutcome.status`: a `MemoryOperationStatus` enum value
- `MemoryOperationOutcome.succeeded`: whether the authoritative operation succeeded
- `MemoryOperationOutcome.memory_id`: affected memory ID, when available
- `MemoryOperationOutcome.detail`: optional diagnostic detail
- `MemoryOperationOutcome.similarity_advisories`: non-blocking scoped semantic
  matches, each with an existing memory ID and vector distance
- `MemoryOperationOutcome.reason`: display string derived from status and detail

**Example:**

```python
# Option 1: Full auto-extraction (recommended)
outcome = manager.store_memory(
    "Had coffee at Starbucks with John on Monday",
    "profile",
    validate=True,
    auto_classify=True,
    auto_extract=True,  # Extracts person, source_type, event_time, strength
)

# Option 2: Manual metadata specification
outcome = manager.store_memory(
    "User likes coffee",
    "profile",
    person="Kenny",
    source_type="conversation",
    strength=8,
    auto_extract=False,  # Don't override provided values
)

if outcome.succeeded:
    print(f"Stored with ID: {outcome.memory_id}")
else:
    print(f"Failed: {outcome.reason}")
```

**Possible reason values:**

- `"stored_successfully"` - Successfully stored
- `"stored_pending_index"` - Authoritative SQL was stored and vector indexing
  will be retried by reconciliation
- `"duplicate_key"` - The explicit stable key already exists
- `"duplicate_found"` - Normalized exact content already exists in the same
  complete scope; semantic similarity alone never produces this status
- `"validation_failed: llm_rejected"` - LLM rejected
- `"validation_failed: too_short"` - Content too short
- `"storage_error: ..."` - Storage error

---

#### `retrieve_similar()`

Retrieve similar memories using semantic search.

```python
memories = manager.retrieve_similar(
    query: str,                # Required - Query text
    top_k: int = 5,           # Number of results to return
    person: Optional[str] = None,        # Filter: specific person
    topic: Optional[str] = None,         # Filter: specific type/topic
    layer: Optional[str] = None,         # Filter: specific layer
)
```

**Return values:**

```python
list[MemorySearchResult]

# Each result keeps semantic ranking separate from the authoritative record:
MemorySearchResult(
    memory=MemoryRecord(
        id=1,
        content="content",
        layer="profile",
        memory_key=None,
        revision=1,
        indexed_revision=1,
        # ... timestamps and metadata
    ),
    distance=0.23,
)
```

**Example:**

```python
results = manager.retrieve_similar(
    query="User food preferences",
    top_k=3,
    person="Kenny",
)

for mem in results:
    print(f"{mem.memory.content} (distance: {mem.distance:.3f})")
```

**Exceptions:**

- `RuntimeError` - Retrieval failed (network, model, etc.)

---

#### `get_memory_by_key()`

Retrieve one project-owned structured record without embedding generation or
semantic ranking.

```python
memory = manager.get_memory_by_key("list:shopping")
```

This returns a validated `MemoryRecord` or `None`. Use it for stable keys;
use `retrieve_similar()` only when relevance discovery is actually intended.

---

#### `update_memory()`

Update an existing memory.

```python
outcome = manager.update_memory(
    memory_id: int,            # Required - Memory ID
    content: Optional[str] = None,       # New content
    layer: Optional[str] = None,         # New layer
    person: Optional[str] = None,        # New related person
    topic: Optional[str] = None,         # New topic
    strength: Optional[int] = None,      # New importance (1-10)
    expected_revision: Optional[int] = None, # Reject a stale update
)
```

Returns `MemoryOperationOutcome`.

**Example:**

```python
outcome = manager.update_memory(
    memory_id=1,
    content="Updated memory content",
    strength=3,
    expected_revision=1,
)
```

**Possible reason values:**

- `"updated_successfully"` - Successfully updated
- `"updated_pending_index"` - The new SQL revision is durable but its vector
  still needs reconciliation
- `"no_changes"` - No changes made
- `"memory_revision_conflict"` - The record changed after it was retrieved
- `"update_error: ..."` - Update failed

---

#### `delete_memory()`

Delete a memory and its vector.

```python
outcome = manager.delete_memory(
    memory_id: int,
    expected_revision: Optional[int] = None,
)
```

Returns `MemoryOperationOutcome`.

Deletion is logically successful once its SQL tombstone is durable. A
`"deleted_pending_index_cleanup"` result means the record is already hidden and
reconciliation will retry vector deletion and final purging.

**Example:**

```python
outcome = manager.delete_memory(1)
```

---

#### `reconcile_index()`

Repair the derived vector index from authoritative SQL state.

```python
result = manager.reconcile_index()
print(result.indexed_memories)
print(result.cleaned_tombstones)
print(result.removed_orphan_vectors)
print(result.failures)
```

The method is idempotent and returns `IndexReconciliationResult`. Individual
repair failures remain pending for a later retry instead of reverting current
memory content.

---

#### `process_memory_action()`

Process memory actions proposed by the reasoning engine.

```python
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryTarget,
    StructuredListOperation,
)

outcome = manager.process_memory_action(
    action: MemoryAction
)
```

**MemoryAction structure:**

```python
MemoryAction(
    action: str,  # "store" / "update" / "delete"
    content: Optional[str],  # None when list_operation carries the mutation
    rationale: str,  # Why this action should be taken
    target: Optional[MemoryTarget],  # Required for update/delete
    list_operation: Optional[StructuredListOperation],
    requires_confirmation: bool,  # Whether confirmation is required
)
```

`update` and `delete` actions fail closed unless `target` contains a stable
memory ID or an explicit scoped key. Targets derived from retrieved memories
should also carry `expected_revision`. Semantic retrieval is not used to choose
which record is mutated.

Shopping and task additions use
`StructuredListOperation(operation="add_items")` with a tuple of items. The
same typed operation creates the first persisted list or updates an existing
exact target. The memory domain owns rendering and item deduplication; callers
must not encode commands in `content`.

**Example:**

```python
action = MemoryAction(
    action="store",
    content="Remember user likes business trips",
    rationale="User mentioned upcoming business trip",
    requires_confirmation=False,
)

outcome = manager.process_memory_action(action)
```

---

#### `get_context_memories()`

Get memories related to a query (for reasoning engine context).

```python
memories = manager.get_context_memories(
    query: str,                # Required - Query
    context_size: int = 3,    # Number of results to return
)
```

**Return values:**

```python
list[MemorySearchResult]
```

**Example:**

```python
context = manager.get_context_memories(
    "Tell me about the user",
    context_size=5,
)

# Application code should retrieve through MemoryManagerGateway, which converts
# these results to the MemoryReference values accepted by reasoning requests.
```

---

#### `get_all_memories()`

Get all memories.

```python
memories = manager.get_all_memories()
```

**Return values:**

```python
list[MemoryRecord]  # Ordered by creation time (newest first)
```

---

#### `close()`

Close all connections. **Must be called after use.**

```python
manager.close()
```

---

## MemoryStore

Low-level storage interface. Typically not used directly, accessed through MemoryManager.

### Initialization

```python
store = MemoryStore(db_path: str)
```

### Methods

#### `create_memory()`

```python
memory_id = store.create_memory(
    content: str,
    layer: str,
    event_time: Optional[int] = None,
    strength: int = 1,
    person: Optional[str] = None,
    source_type: Optional[str] = None,
    topic: Optional[str] = None,
    memory_key: Optional[str] = None,
)
```

#### `get_memories()`

```python
memories = store.get_memories(
    person: Optional[str] = None,
    source_type: Optional[str] = None,
    topic: Optional[str] = None,
)
```

#### `update_memory()`

```python
success = store.update_memory(
    memory_id: int,
    content: Optional[str] = None,
    expected_revision: Optional[int] = None,
    # ... other fields
)
```

#### `delete_memory()`

```python
success = store.delete_memory(
    memory_id: int,
    expected_revision: Optional[int] = None,
)
```

#### `close()`

```python
store.close()
```

---

## MemoryRetriever

Query interface. Typically accessed through MemoryManager.

### Methods

#### `retrieve_similar()`

See MemoryManager.retrieve_similar()

#### `retrieve_by_metadata()`

```python
memories = retriever.retrieve_by_metadata(
    person: Optional[str] = None,
    topic: Optional[str] = None,
    layer: Optional[str] = None,
)
```

#### `retrieve_by_person()`

```python
memories = retriever.retrieve_by_person(
    person: str,
    top_k: int = 10,
)
```

#### `retrieve_by_topic()`

```python
memories = retriever.retrieve_by_topic(
    topic: str,
    top_k: int = 10,
)
```

#### `retrieve_by_layer()`

```python
memories = retriever.retrieve_by_layer(
    layer: str,
    top_k: int = 10,
)
```

#### `retrieve_all()`

```python
memories = retriever.retrieve_all()
```

---

## MemoryValidator

Validation and classification interface.

### Initialization

```python
validator = MemoryValidator(
    model: str = "granite:7b",
    host: str = "http://localhost:11434",
)
```

### Methods

#### `should_store()`

Determine whether content should be stored.

```python
should_store, reason = validator.should_store(content: str)
```

**Return values:**

- `should_store: bool`
- `reason: str` - Reason

**Possible reason values:**

- `"llm_approved"` / `"llm_rejected"`
- `"empty_content"` / `"too_short"`
- `"validation_error: ..."`

---

#### `classify_memory_type()`

Classify memory type.

```python
from voice_concierge.memory.memory_validator import MemoryType

memory_type, reason = validator.classify_memory_type(content: str)
```

**Return values:**

- `memory_type: Optional[MemoryType]` - Classification result
- `reason: str` - Reason

**MemoryType values:**

- `MemoryType.EPISODIC` - Episodic
- `MemoryType.SEMANTIC` - Semantic
- `MemoryType.PROCEDURAL` - Procedural
- `MemoryType.EMOTIONAL` - Emotional
- `MemoryType.REFLECTIVE` - Reflective

---

#### `extract_metadata()`

Extract structured metadata from memory content.

```python
metadata = validator.extract_metadata(content: str)
```

**Return values:**

```python
{
    "person": Optional[str],      # Name of person mentioned (or None)
    "source_type": Optional[str],  # one of: conversation, document, observation, experience
    "event_time": Optional[str],   # ISO timestamp if event time mentioned (or None)
    "strength": int,               # Importance rating 1-10 (default 5)
}
```

**Example:**

```python
metadata = validator.extract_metadata(
    "Had lunch with Alice at the Italian place downtown yesterday"
)

print(metadata)
# Output:
# {
#     "person": "Alice",
#     "source_type": "experience",
#     "event_time": "2026-06-28T12:00:00",
#     "strength": 6
# }
```

---

#### `get_validation_report()`

Get a complete validation report.

```python
report = validator.get_validation_report(content: str)
```

**Return values:**

```python
{
    "should_store": bool,
    "reason": str,
    "memory_type": Optional[str],
    "classification": str,
    "content_length": int,
    "content_stripped_length": int,
    "model": str,
}
```

---

## VectorStore

Vector store interface. Typically not used directly.

### Initialization

```python
store = VectorStore(
    db_path: str,
    dimension: int = 768,
)
```

### Methods

#### `save_vector()`

```python
store.save_vector(
    memory_id: int,
    embedding: List[float],  # 768-dimensional vector
)
```

#### `search_similar()`

```python
results = store.search_similar(
    query_embedding: List[float],
    top_k: int = 3,
)
```

**Return values:**

```python
list[VectorSearchResult]
# [VectorSearchResult(memory_id=1, distance=0.23)]
```

#### `close()`

```python
store.close()
```

---

## EmbeddingService

Embedding generation interface. Typically not used directly.

### Initialization

```python
service = EmbeddingService(
    model_name: str = "granite-embedding:278m"
)
```

### Methods

#### `get_embedding()`

Convert text to vector embedding.

```python
embedding = service.get_embedding(content: str)
```

**Return values:**

```python
List[float]  # 768-dimensional vector
```

---

## Type Definitions

### MemoryType (Enum)

```python
from voice_concierge.memory.memory_validator import MemoryType

MemoryType.EPISODIC    # "episodic"
MemoryType.SEMANTIC    # "semantic"
MemoryType.PROCEDURAL  # "procedural"
MemoryType.EMOTIONAL   # "emotional"
MemoryType.REFLECTIVE  # "reflective"
```

---

## Common Use Cases

### Scenario 1: Simple Store and Retrieve

```python
from voice_concierge.memory import MemoryManager

manager = MemoryManager(...)

# Store
manager.store_memory("User likes coffee", "profile")

# Retrieve
results = manager.retrieve_similar("What does the user like?")

manager.close()
```

### Scenario 2: Integration with Reasoning Engine

```python
# Application code gets typed MemoryReference context through the gateway:
references = gateway.retrieve(user_input, "personal_relevant")
request = ReasoningRequest(transcript=user_input, memories=references)

# Handle results
if response.proposed_memory_action:
    manager.process_memory_action(response.proposed_memory_action)
```

### Scenario 3: Batch Operations

```python
# Batch store
for item in items:
    manager.store_memory(item, "raw", validate=False)

# Batch retrieve
all_memories = manager.get_all_memories()

# Retrieve by type
semantic_memories = manager.retriever.retrieve_by_topic("semantic")
```

### Scenario 4: Auto-Extract Metadata

```python
# Store with automatic metadata extraction
outcome = manager.store_memory(
    "Ran into Sarah at the coffee shop last Tuesday. She mentioned starting a new job at Google.",
    "profile",
    auto_extract=True,  # Automatically extract person, source_type, event_time, strength
)

# The memory is stored with:
# - person: "Sarah"
# - source_type: "observation" or "conversation"
# - event_time: Last Tuesday's timestamp
# - strength: 7 (important information)

# Later, retrieve memories about Sarah
sarah_memories = manager.retriever.retrieve_by_person("Sarah")
```

---

## Error Handling

```python
try:
    outcome = manager.store_memory(...)
    if not outcome.succeeded:
        print(f"Failed: {outcome.reason}")

    memories = manager.retrieve_similar(...)
except RuntimeError as e:
    print(f"Retrieval error: {e}")
finally:
    manager.close()
```

---

## Performance Tips

- Use `auto_classify=False` to speed up storage
- Use `validate=False` to speed up storage (batch operations only)
- Metadata filtering is faster than semantic search
- Limit `top_k` to improve retrieval speed
- Regularly backup the database
