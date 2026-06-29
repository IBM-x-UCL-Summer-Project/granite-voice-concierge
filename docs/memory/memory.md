# Memory Module API Reference

Complete API documentation for the memory module.

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
success, reason, memory_id = manager.store_memory(
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
)
```

**Return values:**
- `success: bool` - Whether successful
- `reason: str` - Status description
- `memory_id: Optional[int]` - Memory ID (None if failed)

**Example:**
```python
# Option 1: Full auto-extraction (recommended)
success, reason, mid = manager.store_memory(
    "Had coffee at Starbucks with John on Monday",
    "profile",
    validate=True,
    auto_classify=True,
    auto_extract=True,  # Extracts person, source_type, event_time, strength
)

# Option 2: Manual metadata specification
success, reason, mid = manager.store_memory(
    "User likes coffee",
    "profile",
    person="Kenny",
    source_type="conversation",
    strength=8,
    auto_extract=False,  # Don't override provided values
)

if success:
    print(f"Stored with ID: {mid}")
else:
    print(f"Failed: {reason}")
```

**Possible reason values:**
- `"stored_successfully"` - Successfully stored
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
List[dict]  # Memory list sorted by similarity

# Structure of each memory:
{
    'id': 1,              # Memory ID
    'content': 'content', # Memory content
    'layer': 'profile',   # Layer
    'created_at': 1234567,# Creation timestamp
    'person': 'Kenny',    # Related person
    'topic': 'semantic',  # Memory type or topic
    'distance': 0.23,     # Similarity distance (lower = more similar)
    'strength': 1,        # Importance/strength
    'event_time': None,   # Event occurrence time
    'last_accessed': None,# Last access time
}
```

**Example:**
```python
results = manager.retrieve_similar(
    query="User food preferences",
    top_k=3,
    person="Kenny",
)

for mem in results:
    print(f"{mem['content']} (distance: {mem['distance']:.3f})")
```

**Exceptions:**
- `RuntimeError` - Retrieval failed (network, model, etc.)

---

#### `update_memory()`

Update an existing memory.

```python
success, reason = manager.update_memory(
    memory_id: int,            # Required - Memory ID
    content: Optional[str] = None,       # New content
    layer: Optional[str] = None,         # New layer
    person: Optional[str] = None,        # New related person
    topic: Optional[str] = None,         # New topic
    strength: Optional[int] = None,      # New importance (1-10)
)
```

**Return values:**
- `success: bool` - Whether successful
- `reason: str` - Status description

**Example:**
```python
success, reason = manager.update_memory(
    memory_id=1,
    content="Updated memory content",
    strength=3,
)
```

**Possible reason values:**
- `"updated_successfully"` - Successfully updated
- `"no_changes"` - No changes made
- `"update_error: ..."` - Update failed

---

#### `delete_memory()`

Delete a memory and its vector.

```python
success, reason = manager.delete_memory(memory_id: int)
```

**Return values:**
- `success: bool`
- `reason: str`

**Example:**
```python
success, reason = manager.delete_memory(1)
```

---

#### `process_memory_action()`

Process memory actions proposed by the reasoning engine.

```python
from voice_concierge.reasoning.types import MemoryAction

success, reason = manager.process_memory_action(
    action: MemoryAction
)
```

**MemoryAction structure:**
```python
MemoryAction(
    action: str,  # "store" / "update" / "delete"
    content: str,  # Content of the action
    rationale: str,  # Why this action should be taken
    requires_confirmation: bool,  # Whether confirmation is required
)
```

**Example:**
```python
action = MemoryAction(
    action="store",
    content="Remember user likes business trips",
    rationale="User mentioned upcoming business trip",
    requires_confirmation=False,
)

success, reason = manager.process_memory_action(action)
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
List[str]  # List of memory contents

# Example:
["User likes pasta", "User works at IBM", "User travels to London next month"]
```

**Example:**
```python
context = manager.get_context_memories(
    "Tell me about the user",
    context_size=5,
)

# For use in reasoning requests
from voice_concierge.reasoning.types import ReasoningRequest

request = ReasoningRequest(
    transcript="User input",
    memories=tuple(context),  # Pass context
)
```

---

#### `get_all_memories()`

Get all memories.

```python
memories = manager.get_all_memories()
```

**Return values:**
```python
List[dict]  # All memories, ordered by creation time (newest first)
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
    # ... other fields
)
```

#### `delete_memory()`
```python
success = store.delete_memory(memory_id: int)
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
List[dict]  # Results
# [
#     {"memory_id": 1, "distance": 0.23},
#     {"memory_id": 5, "distance": 0.45},
# ]
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
# Get context
context = manager.get_context_memories(user_input)

# Create reasoning request
request = ReasoningRequest(
    transcript=user_input,
    memories=tuple(context),
)

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
success, reason, mid = manager.store_memory(
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
    success, reason, mid = manager.store_memory(...)
    if not success:
        print(f"Failed: {reason}")
    
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

