# tests/unit/privacy/test_disclosure.py
# Standard library
from pathlib import Path

# Third-party
import pytest

# Local
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.disclosure import (
    NOT_RETAINED,
    build_report,
    describe_location,
    format_report,
)
from voice_concierge.privacy.factory import build_privacy_centre, default_database_paths
from voice_concierge.privacy.fakes import FakeMemoryArchive
from voice_concierge.privacy.types import (
    LAYER_DESCRIPTIONS,
    PrivacyReport,
    StorageLocation,
    StoredMemory,
)


def _record(identifier: int, layer: str = "semantic") -> dict:
    return {
        "id": identifier,
        "content": f"memory {identifier}",
        "layer": layer,
        "created_at": 1_700_000_000,
    }


@pytest.mark.unit
class TestDescribeLocation:
    def test_reports_an_existing_file_with_its_size(self, tmp_path: Path) -> None:
        target = tmp_path / "memories.sqlite3"
        target.write_bytes(b"x" * 2048)

        location = describe_location("Memories", target, "text")

        assert location.exists is True
        assert location.size_bytes == 2048
        assert location.size_display == "2.0 KB"

    def test_reports_a_missing_file_plainly(self, tmp_path: Path) -> None:
        location = describe_location("Memories", tmp_path / "absent.db", "text")

        assert location.exists is False
        assert location.size_display == "not created yet"

    def test_unreadable_path_does_not_break_the_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A permissions problem must not stop the user seeing anything."""

        def _explode(self) -> bool:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "exists", _explode)
        location = describe_location("Memories", tmp_path / "x.db", "text")

        assert location.exists is False


@pytest.mark.unit
class TestSizeDisplay:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [(512, "512 B"), (2048, "2.0 KB"), (5 * 1024 * 1024, "5.0 MB")],
    )
    def test_sizes_are_shown_in_readable_units(self, size: int, expected: str) -> None:
        location = StorageLocation("n", "p", "d", exists=True, size_bytes=size)
        assert location.size_display == expected

    def test_very_large_sizes_fall_back_to_gigabytes(self) -> None:
        location = StorageLocation("n", "p", "d", exists=True, size_bytes=3 * 1024**3)
        assert location.size_display == "3.0 GB"


@pytest.mark.unit
class TestStoredMemoryDisplay:
    def test_known_layer_is_explained_in_plain_english(self) -> None:
        memory = StoredMemory(1, "a", "semantic")
        assert memory.layer_description == LAYER_DESCRIPTIONS["semantic"]

    def test_unknown_layer_is_named_rather_than_hidden(self) -> None:
        memory = StoredMemory(1, "a", "invented")
        assert "invented" in memory.layer_description

    def test_creation_time_is_shown_as_a_date(self) -> None:
        memory = StoredMemory(1, "a", "semantic", created_at=1_700_000_000)
        assert memory.created_display.endswith("UTC")


@pytest.mark.unit
class TestReport:
    def test_report_counts_memories_and_layers(self, tmp_path: Path) -> None:
        centre = PrivacyCentre(FakeMemoryArchive([_record(1), _record(2, "episodic")]))

        report = build_report(
            centre, memory_db=tmp_path / "m.db", vector_db=tmp_path / "v.db"
        )

        assert report.memory_count == 2
        assert report.counts_by_layer == {"semantic": 1, "episodic": 1}
        assert len(report.locations) == 2

    def test_report_states_what_is_never_stored(self, tmp_path: Path) -> None:
        """The disclosure has to cover absence, not only presence."""
        centre = PrivacyCentre(FakeMemoryArchive([]))

        report = build_report(
            centre, memory_db=tmp_path / "m.db", vector_db=tmp_path / "v.db"
        )

        assert report.not_retained == NOT_RETAINED
        joined = " ".join(report.not_retained).lower()
        assert "audio" in joined
        assert "conversation history" in joined

    def test_formatted_report_mentions_counts_paths_and_exclusions(self) -> None:
        report = PrivacyReport(
            memory_count=2,
            counts_by_layer={"semantic": 2},
            locations=(
                StorageLocation(
                    "Memories", "/tmp/m.db", "readable text", exists=True, size_bytes=10
                ),
            ),
            not_retained=("Recorded audio.",),
        )

        text = format_report(report)

        assert "Memories stored: 2" in text
        assert "2 semantic" in text
        assert "/tmp/m.db" in text
        assert "Recorded audio." in text

    def test_formatted_report_of_an_empty_store_still_explains_itself(self) -> None:
        text = format_report(PrivacyReport(memory_count=0))

        assert "Memories stored: 0" in text
        assert "What is never stored:" in text


@pytest.mark.unit
class TestFactory:
    def test_builds_a_centre_over_a_supplied_manager(self) -> None:
        centre = build_privacy_centre(FakeMemoryArchive([_record(1)]))

        assert isinstance(centre, PrivacyCentre)
        assert len(centre.list_memories()) == 1

    def test_default_paths_point_at_the_local_databases(self) -> None:
        memory_db, vector_db = default_database_paths()

        assert memory_db.name.endswith(".sqlite3")
        assert vector_db.name.endswith(".sqlite3")


@pytest.mark.unit
class TestLayerCoverage:
    """Every layer the system writes must be explained, not just named."""

    @pytest.mark.parametrize(
        "layer",
        ["episodic", "semantic", "procedural", "emotional", "reflective", "profile"],
    )
    def test_every_written_layer_has_a_plain_english_description(
        self, layer: str
    ) -> None:
        assert layer in LAYER_DESCRIPTIONS
        assert StoredMemory(1, "a", layer).layer_description != f"Stored as '{layer}'."
