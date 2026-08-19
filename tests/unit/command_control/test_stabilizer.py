# Third-party
import pytest

# Local
from voice_concierge.command_control.fakes import FakeCommandSpotter
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.stabilizer import StableCommandSpotter
from voice_concierge.command_control.types import CommandEvent

_FRAME = b"frame"


class _FakeClock:
    """A clock the test advances by hand, so timing is deterministic."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ResettableSpotter(FakeCommandSpotter):
    def __init__(self, events) -> None:
        super().__init__(events)
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1


def _event(command: str) -> CommandEvent:
    return CommandEvent(command=command, phrase=command)


def _spotter(
    events: list[CommandEvent | None], clock: _FakeClock
) -> StableCommandSpotter:
    return StableCommandSpotter(
        FakeCommandSpotter(events),
        confirm_window=1.0,
        cooldown=1.5,
        required_sightings=2,
        clock=clock,
    )


@pytest.mark.unit
class TestConfirmation:
    """A command must be seen twice in the window before it fires."""

    def test_single_sighting_is_suppressed(self) -> None:
        """A lone hallucination on noise never reaches the caller."""
        clock = _FakeClock()
        spotter = _spotter([_event("back")], clock)

        assert spotter.process(_FRAME) is None

    def test_second_sighting_within_window_confirms(self) -> None:
        clock = _FakeClock()
        spotter = _spotter([_event("next"), _event("next")], clock)

        assert spotter.process(_FRAME) is None
        clock.advance(0.2)
        event = spotter.process(_FRAME)

        assert event is not None
        assert event.command == "next"

    def test_second_sighting_after_window_restarts_confirmation(self) -> None:
        """Two sightings too far apart are unrelated, not a confirmation."""
        clock = _FakeClock()
        spotter = _spotter([_event("next"), _event("next")], clock)

        assert spotter.process(_FRAME) is None
        clock.advance(5.0)  # beyond confirm_window
        assert spotter.process(_FRAME) is None

    def test_different_command_restarts_confirmation(self) -> None:
        clock = _FakeClock()
        spotter = _spotter([_event("next"), _event("back")], clock)

        assert spotter.process(_FRAME) is None
        clock.advance(0.1)
        assert spotter.process(_FRAME) is None

    def test_no_recognition_passes_through_as_none(self) -> None:
        clock = _FakeClock()
        spotter = _spotter([None], clock)

        assert spotter.process(_FRAME) is None

    def test_trusted_capture_can_emit_on_one_sighting(self) -> None:
        clock = _FakeClock()
        spotter = StableCommandSpotter(
            FakeCommandSpotter([_event("pause"), _event("pause")]),
            required_sightings=1,
            cooldown=1.5,
            clock=clock,
        )

        assert spotter.process(_FRAME) == _event("pause")
        clock.advance(0.1)
        assert spotter.process(_FRAME) is None

    def test_required_sightings_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            StableCommandSpotter(FakeCommandSpotter(), required_sightings=0)

    def test_default_rejects_an_early_hypothesis_that_vosk_corrects(self) -> None:
        clock = _FakeClock()
        spotter = StableCommandSpotter(
            FakeCommandSpotter(
                [
                    _event("faster"),
                    _event("faster"),
                    _event("back"),
                    _event("back"),
                    _event("back"),
                ]
            ),
            clock=clock,
        )

        observed = []
        for _ in range(5):
            observed.append(spotter.process(_FRAME))
            clock.advance(0.1)

        assert observed[:4] == [None, None, None, None]
        assert observed[4] == _event("back")

    def test_emitting_discards_the_rest_of_the_recognizer_utterance(self) -> None:
        clock = _FakeClock()
        inner = _ResettableSpotter([_event("pause")] * 3)
        spotter = StableCommandSpotter(inner, clock=clock)

        assert spotter.process(_FRAME) is None
        assert spotter.process(_FRAME) is None
        assert spotter.process(_FRAME) == _event("pause")

        assert inner.reset_count == 1


@pytest.mark.unit
class TestCooldown:
    """After firing, the same command is refused for the cooldown."""

    def test_repeat_within_cooldown_is_dropped(self) -> None:
        """The partial+final and trailing-audio repeats do not act twice."""
        clock = _FakeClock()
        spotter = _spotter([_event("back")] * 4, clock)

        assert spotter.process(_FRAME) is None  # first sighting
        clock.advance(0.1)
        assert spotter.process(_FRAME) is not None  # confirmed, fires

        clock.advance(0.2)
        assert spotter.process(_FRAME) is None  # repeat, still cooling down
        clock.advance(0.2)
        assert spotter.process(_FRAME) is None

    def test_same_command_fires_again_after_cooldown(self) -> None:
        """A command genuinely spoken again later still gets through."""
        clock = _FakeClock()
        spotter = _spotter([_event("next")] * 4, clock)

        spotter.process(_FRAME)
        clock.advance(0.1)
        assert spotter.process(_FRAME) is not None  # first fire

        clock.advance(5.0)  # past the cooldown
        assert spotter.process(_FRAME) is None  # needs confirming again
        clock.advance(0.1)
        assert spotter.process(_FRAME) is not None  # fires again

    def test_a_different_command_is_not_blocked_by_the_cooldown(self) -> None:
        clock = _FakeClock()
        spotter = _spotter(
            [_event("next"), _event("next"), _event("stop"), _event("stop")], clock
        )

        spotter.process(_FRAME)
        clock.advance(0.1)
        assert spotter.process(_FRAME) is not None  # "next" fires

        clock.advance(0.1)  # well inside "next"'s cooldown
        assert spotter.process(_FRAME) is None  # "stop" first sighting
        clock.advance(0.1)
        event = spotter.process(_FRAME)

        assert event is not None
        assert event.command == "stop"


@pytest.mark.unit
class TestConformance:
    def test_satisfies_command_spotter_protocol(self) -> None:
        assert isinstance(StableCommandSpotter(FakeCommandSpotter()), CommandSpotter)

    def test_defaults_to_the_real_clock(self) -> None:
        """Constructed without a clock it still works, using time.monotonic."""
        spotter = StableCommandSpotter(FakeCommandSpotter([_event("stop")] * 3))

        assert spotter.process(_FRAME) is None
        assert spotter.process(_FRAME) is None
        event = spotter.process(_FRAME)  # real clock: elapsed is ~0, so within window

        assert event is not None
        assert event.command == "stop"

    def test_reset_discards_unconfirmed_sighting(self) -> None:
        clock = _FakeClock()
        spotter = _spotter([_event("yes"), _event("yes")], clock)

        assert spotter.process(_FRAME) is None
        spotter.reset()
        clock.advance(0.1)

        assert spotter.process(_FRAME) is None
