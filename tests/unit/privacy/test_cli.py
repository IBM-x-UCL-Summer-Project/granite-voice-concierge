# tests/unit/privacy/test_cli.py
# Standard library
import io
import json

# Third-party
import pytest

# Local
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.cli import CONFIRM_WORD, format_memory, main
from voice_concierge.privacy.fakes import FakeMemoryArchive
from voice_concierge.privacy.types import StoredMemory


def _record(identifier: int, content: str, **overrides) -> dict:
    record = {
        "id": identifier,
        "content": content,
        "layer": "semantic",
        "created_at": 1_700_000_000 + identifier,
        "topic": "food",
        "source_type": "conversation",
    }
    record.update(overrides)
    return record


def _run(argv, records=None, *, replies=None, archive=None):
    """Run the CLI against a fake archive, returning (exit code, output)."""
    store = archive if archive is not None else FakeMemoryArchive(records or [])
    answers = list(replies or [])
    out = io.StringIO()

    def _confirm(prompt: str) -> str:
        return answers.pop(0) if answers else ""

    code = main(argv, centre=PrivacyCentre(store), confirm=_confirm, stdout=out)
    return code, out.getvalue(), store


@pytest.mark.unit
class TestStorageSummary:
    def test_no_command_explains_what_is_stored(self) -> None:
        code, out, _ = _run([], [_record(1, "likes tea")])

        assert code == 0
        assert "What this assistant stores on this device" in out
        assert "Memories stored: 1" in out

    def test_summary_states_what_is_never_stored(self) -> None:
        """The point of the centre is disclosure, not only control."""
        _, out, _ = _run([], [])

        assert "What is never stored:" in out
        assert "audio" in out.lower()


@pytest.mark.unit
class TestList:
    def test_lists_stored_memories(self) -> None:
        code, out, _ = _run(["list"], [_record(1, "likes tea")])

        assert code == 0
        assert "[1] likes tea" in out
        assert "1 memories." in out

    def test_empty_store_says_so(self) -> None:
        _, out, _ = _run(["list"], [])

        assert "Nothing is stored that matches." in out

    def test_search_narrows_the_list(self) -> None:
        _, out, _ = _run(
            ["list", "--search", "tea"], [_record(1, "likes tea"), _record(2, "coffee")]
        )

        assert "likes tea" in out
        assert "coffee" not in out

    def test_layer_filter_narrows_the_list(self) -> None:
        _, out, _ = _run(
            ["list", "--layer", "episodic"],
            [_record(1, "a"), _record(2, "b", layer="episodic")],
        )

        assert "[2]" in out
        assert "[1]" not in out

    def test_verbose_shows_dates_and_sources(self) -> None:
        _, out, _ = _run(["list", "-v"], [_record(1, "likes tea")])

        assert "stored " in out
        assert "topic: food" in out
        assert "learned from: conversation" in out


@pytest.mark.unit
class TestFormatMemory:
    def test_verbose_omits_absent_details(self) -> None:
        text = format_memory(
            StoredMemory(1, "a", "semantic", created_at=1), verbose=True
        )

        assert "topic:" not in text
        assert "learned from:" not in text


@pytest.mark.unit
class TestExport:
    def test_export_prints_valid_json(self) -> None:
        code, out, _ = _run(["export"], [_record(1, "likes tea")])

        assert code == 0
        assert json.loads(out)[0]["content"] == "likes tea"

    def test_export_of_an_empty_store_is_an_empty_list(self) -> None:
        _, out, _ = _run(["export"], [])

        assert json.loads(out) == []


@pytest.mark.unit
class TestEdit:
    def test_corrects_a_memory(self) -> None:
        code, out, store = _run(
            ["edit", "1", "likes coffee"], [_record(1, "likes tea")]
        )

        assert code == 0
        assert "Updated: [1] likes coffee" in out
        assert store.records[0]["content"] == "likes coffee"

    def test_unknown_id_fails_loudly(self) -> None:
        code, out, _ = _run(["edit", "9", "x"], [_record(1, "a")])

        assert code == 1
        assert "No memory with id 9" in out

    def test_blank_content_is_refused(self) -> None:
        code, out, store = _run(["edit", "1", "  "], [_record(1, "likes tea")])

        assert code == 1
        assert "empty" in out
        assert store.records[0]["content"] == "likes tea"  # untouched


@pytest.mark.unit
class TestDelete:
    def test_shows_the_memory_then_deletes_on_confirmation(self) -> None:
        code, out, store = _run(
            ["delete", "1"], [_record(1, "likes tea")], replies=["y"]
        )

        assert code == 0
        assert "[1] likes tea" in out  # the user saw what would go
        assert "Deleted." in out
        assert store.records == []

    def test_declining_leaves_the_memory_alone(self) -> None:
        code, out, store = _run(
            ["delete", "1"], [_record(1, "likes tea")], replies=["n"]
        )

        assert code == 0
        assert "Left unchanged." in out
        assert len(store.records) == 1

    def test_silence_is_not_taken_as_consent(self) -> None:
        """An empty answer must never delete."""
        _, out, store = _run(["delete", "1"], [_record(1, "a")], replies=[""])

        assert "Left unchanged." in out
        assert len(store.records) == 1

    def test_yes_flag_skips_the_prompt(self) -> None:
        code, out, store = _run(["delete", "1", "-y"], [_record(1, "a")])

        assert code == 0
        assert "Deleted." in out
        assert store.records == []

    def test_unknown_id_reports_and_fails(self) -> None:
        code, out, _ = _run(["delete", "9"], [_record(1, "a")])

        assert code == 1
        assert "No memory with id 9" in out


@pytest.mark.unit
class TestForgetAll:
    def test_typed_confirmation_erases_everything(self) -> None:
        code, out, store = _run(
            ["forget-all"],
            [_record(1, "a"), _record(2, "b")],
            replies=[CONFIRM_WORD],
        )

        assert code == 0
        assert "Erased 2 memories." in out
        assert store.records == []

    def test_warns_before_asking(self) -> None:
        _, out, _ = _run(["forget-all"], [_record(1, "a")], replies=[CONFIRM_WORD])

        assert "cannot be undone" in out

    def test_a_plain_yes_is_not_enough(self) -> None:
        """Erasing everything needs the word, not a keypress."""
        code, out, store = _run(["forget-all"], [_record(1, "a")], replies=["y"])

        assert code == 0
        assert "Left unchanged." in out
        assert len(store.records) == 1

    def test_empty_store_needs_no_confirmation(self) -> None:
        code, out, _ = _run(["forget-all"], [])

        assert code == 0
        assert "nothing to erase" in out

    def test_yes_flag_skips_the_typed_confirmation(self) -> None:
        code, out, store = _run(["forget-all", "-y"], [_record(1, "a")])

        assert code == 0
        assert "Erased 1 memories." in out
        assert store.records == []


@pytest.mark.unit
class TestFailureReporting:
    def test_backend_failure_reports_and_returns_nonzero(self) -> None:
        """A privacy action that did not happen must not look like one that did."""
        code, out, _ = _run(["list"], archive=FakeMemoryArchive(failing=True))

        assert code == 1
        assert "Could not complete that" in out


@pytest.mark.unit
def test_module_entry_point_is_importable() -> None:
    """`python -m voice_concierge.privacy` must resolve to the CLI."""
    import voice_concierge.privacy.__main__ as entry

    assert entry.main is main
