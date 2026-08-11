# Third-party
import pytest

# Local
from voice_concierge.command_control.debounce import DebouncingCommandSpotter
from voice_concierge.command_control.fakes import FakeCommandSpotter
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.types import CommandEvent

_FRAME = b"frame"


def _stop() -> CommandEvent:
    return CommandEvent(command="stop", phrase="stop")


def _pause() -> CommandEvent:
    return CommandEvent(command="pause", phrase="pause")


def _drive(spotter: DebouncingCommandSpotter, events) -> list[CommandEvent]:
    """Feed a script of inner results and collect what the debouncer emits."""
    emitted: list[CommandEvent] = []
    for _ in events:
        result = spotter.process(_FRAME)
        if result is not None:
            emitted.append(result)
    return emitted


class TestDebouncingCommandSpotter:
    """Unit tests for the confirm-across-frames debouncer."""

    @pytest.mark.unit
    def test_single_hit_is_suppressed(self) -> None:
        """One recognition alone is not enough to emit."""
        inner = FakeCommandSpotter([_stop()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=10)

        assert _drive(spotter, [1]) == []

    @pytest.mark.unit
    def test_two_consecutive_hits_confirm(self) -> None:
        """The same command twice in a row is emitted once (on the second)."""
        inner = FakeCommandSpotter([_stop(), _stop()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=10)

        emitted = _drive(spotter, [1, 2])

        assert [e.command for e in emitted] == ["stop"]

    @pytest.mark.unit
    def test_hits_accumulate_across_none_frames_within_window(self) -> None:
        """None frames between matching hits do not reset the streak."""
        inner = FakeCommandSpotter([_stop(), None, _stop()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=10)

        emitted = _drive(spotter, [1, 2, 3])

        assert [e.command for e in emitted] == ["stop"]

    @pytest.mark.unit
    def test_streak_resets_after_too_many_idle_frames(self) -> None:
        """A gap longer than the window resets the streak, so no emit."""
        inner = FakeCommandSpotter([_stop(), None, None, _stop()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=2)

        emitted = _drive(spotter, [1, 2, 3, 4])

        assert emitted == []  # the two hits were more than `window` apart

    @pytest.mark.unit
    def test_different_command_resets_streak(self) -> None:
        """A different command breaks the streak rather than confirming."""
        inner = FakeCommandSpotter([_stop(), _pause()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=10)

        assert _drive(spotter, [1, 2]) == []

    @pytest.mark.unit
    def test_emits_again_after_a_fresh_confirmation(self) -> None:
        """After emitting, a new confirmation is required for the next event."""
        inner = FakeCommandSpotter([_stop(), _stop(), _stop(), _stop()])
        spotter = DebouncingCommandSpotter(inner, confirm=2, window=10)

        emitted = _drive(spotter, [1, 2, 3, 4])

        assert [e.command for e in emitted] == ["stop", "stop"]

    @pytest.mark.unit
    def test_satisfies_command_spotter_protocol(self) -> None:
        spotter = DebouncingCommandSpotter(FakeCommandSpotter())
        assert isinstance(spotter, CommandSpotter)
