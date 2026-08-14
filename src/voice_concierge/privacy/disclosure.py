"""Explain what this assistant keeps on the device, and what it does not.

The issue behind this package asks for storage to be explained clearly, not just
made editable. A person cannot meaningfully consent to, or clear out, data they
cannot see, so the disclosure is built from the real files on disk (their paths,
whether they exist, how large they are) rather than from prose that could drift
away from what the code actually does.

It is equally explicit about what is *not* kept. Conversation history and
spoken-preference state live in process memory only and are gone when the
assistant exits, and saying so plainly is part of an honest answer.
"""

# Standard library
from pathlib import Path

# Local
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.types import PrivacyReport, StorageLocation

#: Things the assistant handles in the moment but deliberately never writes down.
NOT_RETAINED: tuple[str, ...] = (
    "Recorded audio. Speech is transcribed and the audio is discarded; no "
    "recording is written to disk.",
    "Conversation history. Recent turns are held in memory to keep a "
    "conversation coherent and are lost when the assistant exits.",
    "Spoken preferences such as pace and accessibility settings, which apply to "
    "the running session only.",
    "Anything sent off this device. All processing, including the language "
    "model, runs locally.",
)


def describe_location(name: str, path: Path, description: str) -> StorageLocation:
    """Describe one file on disk, whether or not it has been created yet."""
    try:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
    except OSError:  # unreadable path: report it rather than failing the summary
        exists, size = False, 0
    return StorageLocation(
        name=name,
        path=str(path),
        description=description,
        exists=exists,
        size_bytes=size,
    )


def build_report(
    centre: PrivacyCentre, *, memory_db: Path, vector_db: Path
) -> PrivacyReport:
    """Assemble a full account of what is stored, from the live files."""
    memories = centre.list_memories()
    return PrivacyReport(
        memory_count=len(memories),
        counts_by_layer=centre.counts_by_layer(),
        locations=(
            describe_location(
                "Memories",
                memory_db,
                "The things the assistant has remembered, as readable text.",
            ),
            describe_location(
                "Search index",
                vector_db,
                "Numerical representations of those memories, used to find a "
                "relevant one. Removed with the memory it belongs to.",
            ),
        ),
        not_retained=NOT_RETAINED,
    )


def format_report(report: PrivacyReport) -> str:
    """Render a report as plain text a person can read aloud or scan."""
    lines = [
        "What this assistant stores on this device",
        "",
        f"Memories stored: {report.memory_count}",
    ]
    for layer, count in sorted(report.counts_by_layer.items()):
        lines.append(f"  {count} {layer}")
    lines.append("")
    lines.append("Where it is kept:")
    for location in report.locations:
        lines.append(f"  {location.name} ({location.size_display})")
        lines.append(f"    {location.path}")
        lines.append(f"    {location.description}")
    lines.append("")
    lines.append("What is never stored:")
    for item in report.not_retained:
        lines.append(f"  - {item}")
    return "\n".join(lines)
