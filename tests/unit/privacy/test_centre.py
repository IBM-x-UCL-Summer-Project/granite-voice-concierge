# tests/unit/privacy/test_centre.py
# Third-party
import pytest

# Local
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.privacy.fakes import FakeMemoryArchive
from voice_concierge.privacy.interfaces import MemoryArchive


def _record(identifier: int, content: str, **overrides) -> dict:
    record = {
        "id": identifier,
        "content": content,
        "layer": "semantic",
        "created_at": 1_700_000_000 + identifier,
        "topic": "food",
        "person": "user",
        "source_type": "conversation",
    }
    record.update(overrides)
    return record


def _centre(records: list[dict] | None = None) -> PrivacyCentre:
    return PrivacyCentre(FakeMemoryArchive(records or []))


@pytest.mark.unit
class TestReview:
    def test_lists_stored_memories_newest_first(self) -> None:
        centre = _centre([_record(1, "older"), _record(2, "newer")])

        contents = [item.content for item in centre.list_memories()]

        assert contents == ["newer", "older"]

    def test_lists_nothing_when_nothing_is_stored(self) -> None:
        assert _centre().list_memories() == ()

    def test_filters_by_layer(self) -> None:
        centre = _centre(
            [_record(1, "a", layer="episodic"), _record(2, "b", layer="semantic")]
        )

        found = centre.list_memories(layer="episodic")

        assert [item.content for item in found] == ["a"]

    def test_search_matches_content_ignoring_case(self) -> None:
        centre = _centre([_record(1, "Likes Tea"), _record(2, "dislikes coffee")])

        found = centre.list_memories(search="TEA")

        assert [item.identifier for item in found] == [1]

    def test_empty_search_is_not_treated_as_a_filter(self) -> None:
        centre = _centre([_record(1, "a"), _record(2, "b")])

        assert len(centre.list_memories(search="")) == 2

    def test_memory_without_a_timestamp_still_lists(self) -> None:
        """A record missing fields must not break the review screen."""
        centre = PrivacyCentre(FakeMemoryArchive([{"id": 3, "content": "bare"}]))

        item = centre.list_memories()[0]

        assert item.layer == "unknown"
        assert item.created_display == "unknown date"

    def test_gets_one_memory_by_id(self) -> None:
        centre = _centre([_record(1, "a"), _record(2, "b")])

        found = centre.get_memory(2)

        assert found is not None
        assert found.content == "b"

    def test_unknown_id_returns_none(self) -> None:
        assert _centre([_record(1, "a")]).get_memory(99) is None

    def test_counts_memories_by_layer(self) -> None:
        centre = _centre(
            [
                _record(1, "a", layer="episodic"),
                _record(2, "b", layer="semantic"),
                _record(3, "c", layer="semantic"),
            ]
        )

        assert centre.counts_by_layer() == {"semantic": 2, "episodic": 1}


@pytest.mark.unit
class TestEdit:
    def test_corrects_a_memory_and_returns_it(self) -> None:
        centre = _centre([_record(1, "likes coffee")])

        updated = centre.edit_memory(1, "likes tea")

        assert updated.content == "likes tea"

    def test_content_is_trimmed(self) -> None:
        centre = _centre([_record(1, "a")])

        assert centre.edit_memory(1, "  spaced  ").content == "spaced"

    def test_blank_content_is_refused(self) -> None:
        """Blanking a memory is not a way to delete it."""
        centre = _centre([_record(1, "a")])

        with pytest.raises(PrivacyError, match="empty"):
            centre.edit_memory(1, "   ")

    def test_unknown_id_reports_clearly(self) -> None:
        centre = _centre([_record(1, "a")])

        with pytest.raises(PrivacyError, match="No memory with id 99"):
            centre.edit_memory(99, "new")

    def test_backend_reason_is_surfaced(self) -> None:
        class _Refusing(FakeMemoryArchive):
            def update_memory(self, memory_id, content=None):
                return False, "database_locked"

        centre = PrivacyCentre(_Refusing([_record(1, "a")]))

        with pytest.raises(PrivacyError, match="database_locked"):
            centre.edit_memory(1, "new")

    def test_success_without_a_readable_row_is_reported(self) -> None:
        """Never claim a change that cannot be read back."""

        class _Vanishing(FakeMemoryArchive):
            def update_memory(self, memory_id, content=None):
                self.records.clear()
                return True, "updated_successfully"

        centre = PrivacyCentre(_Vanishing([_record(1, "a")]))

        with pytest.raises(PrivacyError, match="cannot be read back"):
            centre.edit_memory(1, "new")


@pytest.mark.unit
class TestDelete:
    def test_deletes_one_memory(self) -> None:
        archive = FakeMemoryArchive([_record(1, "a"), _record(2, "b")])
        centre = PrivacyCentre(archive)

        centre.delete_memory(1)

        assert [record["id"] for record in archive.records] == [2]

    def test_deleting_an_unknown_id_reports_clearly(self) -> None:
        with pytest.raises(PrivacyError, match="No memory with id 5"):
            _centre([_record(1, "a")]).delete_memory(5)

    def test_delete_all_removes_everything_and_counts_it(self) -> None:
        archive = FakeMemoryArchive([_record(i, f"m{i}") for i in range(1, 4)])
        centre = PrivacyCentre(archive)

        assert centre.delete_all() == 3
        assert archive.records == []

    def test_delete_all_on_an_empty_store_removes_nothing(self) -> None:
        assert _centre().delete_all() == 0

    def test_partial_delete_reports_how_many_were_removed(self) -> None:
        """A half-finished erase must never be reported as complete."""

        class _FailsOnSecond(FakeMemoryArchive):
            def __init__(self, records):
                super().__init__(records)
                self.calls = 0

            def delete_memory(self, memory_id):
                self.calls += 1
                if self.calls > 1:
                    return False, "database_locked"
                return super().delete_memory(memory_id)

        centre = PrivacyCentre(_FailsOnSecond([_record(1, "a"), _record(2, "b")]))

        with pytest.raises(PrivacyError, match="Removed 1 memories, then stopped"):
            centre.delete_all()


@pytest.mark.unit
class TestExportAndFailures:
    def test_export_returns_readable_records(self) -> None:
        centre = _centre([_record(1, "likes tea")])

        exported = centre.export_memories()

        assert exported[0]["content"] == "likes tea"
        assert exported[0]["created"].endswith("UTC")

    def test_export_of_an_empty_store_is_empty(self) -> None:
        assert _centre().export_memories() == []

    def test_archive_failure_is_reported_as_a_privacy_error(self) -> None:
        centre = PrivacyCentre(FakeMemoryArchive(failing=True))

        with pytest.raises(PrivacyError, match="archive unavailable"):
            centre.list_memories()

    def test_unexpected_backend_failure_is_wrapped(self) -> None:
        class _Exploding:
            def get_all_memories(self):
                raise RuntimeError("disk on fire")

            def update_memory(self, memory_id, content=None):
                return False, ""

            def delete_memory(self, memory_id):
                return False, ""

        with pytest.raises(PrivacyError, match="could not be read"):
            PrivacyCentre(_Exploding()).list_memories()


@pytest.mark.unit
class TestConformance:
    def test_fake_satisfies_the_archive_protocol(self) -> None:
        assert isinstance(FakeMemoryArchive(), MemoryArchive)
