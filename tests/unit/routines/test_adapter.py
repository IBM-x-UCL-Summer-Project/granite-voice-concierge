# tests/unit/routines/test_adapter.py
# Third-party
import pytest

# Local
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.errors import RoutineError
from voice_concierge.routines.types import Routine, RoutineStep


def _routine(name: str = "tea", n: int = 2) -> Routine:
    return Routine(
        name=name, steps=tuple(RoutineStep(f"step {i}") for i in range(1, n + 1))
    )


class _Provider:
    """Minimal provider returning configured candidates."""

    def __init__(
        self, candidates: tuple[Routine, ...] = (), *, error: bool = False
    ) -> None:
        self._candidates = candidates
        self._error = error

    def find_candidates(self, request: str) -> tuple[Routine, ...]:
        if self._error:
            raise RoutineError("backend down")
        return self._candidates


def _event(command: str) -> CommandEvent:
    return CommandEvent(command=command, phrase=command)


@pytest.mark.unit
class TestStartRoutine:
    def test_single_match_starts_and_speaks_first_step(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        said = adapter.start_routine("make tea")
        assert "Step 1 of 2" in said
        assert "step 1" in said

    def test_no_match_speaks_not_found(self) -> None:
        adapter = RoutineCommandAdapter(_Provider(()))
        assert adapter.start_routine("x") == "I don't have a routine for that."

    def test_backend_error_speaks_generic_fallback(self) -> None:
        adapter = RoutineCommandAdapter(_Provider(error=True))
        assert adapter.start_routine("x") == "I couldn't load that routine right now."

    def test_multiple_matches_asks(self) -> None:
        adapter = RoutineCommandAdapter(
            _Provider((_routine("pasta bake"), _routine("pasta salad")))
        )
        said = adapter.start_routine("pasta")
        assert "pasta bake" in said and "pasta salad" in said

    def test_resolve_choice_by_name(self) -> None:
        adapter = RoutineCommandAdapter(
            _Provider((_routine("pasta bake"), _routine("pasta salad")))
        )
        adapter.start_routine("pasta")
        said = adapter.resolve_choice("the pasta salad please")
        assert "Step 1 of 2" in said  # pasta salad started

    def test_resolve_choice_unmatched_defaults_to_most_recent(self) -> None:
        adapter = RoutineCommandAdapter(
            _Provider((_routine("first"), _routine("second")))
        )
        adapter.start_routine("pasta")
        said = adapter.resolve_choice("neither of those")
        assert "Step 1 of 2" in said  # defaulted to first (most recent)

    def test_resolve_choice_without_pending_is_noop(self) -> None:
        adapter = RoutineCommandAdapter(_Provider(()))
        assert adapter.resolve_choice("anything") == "There's nothing to choose."


@pytest.mark.unit
class TestHandleCommand:
    def test_command_before_start_reports_no_routine(self) -> None:
        adapter = RoutineCommandAdapter(_Provider(()))
        assert adapter.handle_command(_event("next")) == "No routine is running."

    def test_next_speaks_next_step(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        said = adapter.handle_command(_event("next"))
        assert "Step 2 of 2" in said

    def test_next_past_end_speaks_last_step_message(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(n=1),)))
        adapter.start_routine("tea")
        assert adapter.handle_command(_event("next")) == "That was the last step."

    def test_pause_and_resume_phrases(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        assert adapter.handle_command(_event("pause")).startswith("Paused.")
        assert adapter.handle_command(_event("resume")).startswith("Resuming.")

    def test_back_at_start_phrase(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        assert adapter.handle_command(_event("back")).startswith("You're at the start.")

    def test_stop_phrase(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        assert adapter.handle_command(_event("stop")) == "Routine stopped."

    def test_repeat_phrase(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        adapter.handle_command(_event("next"))
        assert "Step 2 of 2" in adapter.handle_command(_event("repeat"))

    def test_command_after_stop_reports_not_active(self) -> None:
        adapter = RoutineCommandAdapter(_Provider((_routine(),)))
        adapter.start_routine("tea")
        adapter.handle_command(_event("stop"))
        assert adapter.handle_command(_event("next")) == "No routine is running."


@pytest.mark.unit
def test_provider_without_find_candidates_uses_get_routine() -> None:
    from voice_concierge.routines.fakes import StaticRoutineProvider

    adapter = RoutineCommandAdapter(StaticRoutineProvider({"tea": _routine()}))
    assert "Step 1 of 2" in adapter.start_routine("tea")
    assert adapter.start_routine("unknown") == "I don't have a routine for that."


@pytest.mark.unit
def test_new_start_request_clears_stale_pending() -> None:
    """A fresh start_routine abandons a still-pending disambiguation."""

    class _Mutable:
        def __init__(self) -> None:
            self.candidates: tuple = ()

        def find_candidates(self, request: str) -> tuple:
            return self.candidates

    provider = _Mutable()
    provider.candidates = (_routine("a"), _routine("b"))
    adapter = RoutineCommandAdapter(provider)
    adapter.start_routine("x")  # multiple matches -> pending set, asks

    provider.candidates = ()  # nothing matches now
    assert adapter.start_routine("y") == "I don't have a routine for that."
    # the old pending was cleared, so there is nothing left to resolve
    assert adapter.resolve_choice("a") == "There's nothing to choose."
