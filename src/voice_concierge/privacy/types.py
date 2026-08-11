"""Value types for reviewing and controlling locally stored data."""

# Standard library
from dataclasses import dataclass, field
from datetime import datetime, timezone

#: Layers the memory system stores, with what each one means in plain English.
LAYER_DESCRIPTIONS: dict[str, str] = {
    "episodic": "Things that happened, such as something you did or said.",
    "semantic": "Facts about you, such as a preference or a name.",
    "procedural": "How you like things done, such as the steps of a routine.",
}


@dataclass(frozen=True)
class StoredMemory:
    """One stored memory, as shown to the person it is about.

    A read-only view over a stored row: the privacy centre presents these rather
    than raw database dictionaries, so the display cannot accidentally depend on
    the storage schema.
    """

    identifier: int
    content: str
    layer: str
    created_at: int | None = None
    topic: str | None = None
    person: str | None = None
    source_type: str | None = None

    @property
    def layer_description(self) -> str:
        """Explain this memory's layer, or name it if it is unrecognised."""
        return LAYER_DESCRIPTIONS.get(self.layer, f"Stored as '{self.layer}'.")

    @property
    def created_display(self) -> str:
        """The creation time as a readable date, or a clear stand-in."""
        if self.created_at is None:
            return "unknown date"
        moment = datetime.fromtimestamp(self.created_at, tz=timezone.utc)
        return moment.strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True)
class StorageLocation:
    """One place data is kept on this device."""

    name: str
    path: str
    description: str
    exists: bool
    size_bytes: int = 0

    @property
    def size_display(self) -> str:
        """The size in units a person reads, rather than raw bytes."""
        if not self.exists:
            return "not created yet"
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"  # pragma: no cover - loop always returns first


@dataclass(frozen=True)
class PrivacyReport:
    """A full account of what this assistant keeps about you, and where."""

    memory_count: int
    locations: tuple[StorageLocation, ...] = ()
    #: Data the assistant handles but deliberately does not keep.
    not_retained: tuple[str, ...] = ()
    counts_by_layer: dict[str, int] = field(default_factory=dict)
