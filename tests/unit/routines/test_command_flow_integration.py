"""End-to-end command flow within scope: both input paths drive the routine.

Wires the real command_control spotting/parsing to the real routine adapter and
session (only the recognizer and step source are fakes), verifying that a spoken
navigation command actually moves the routine and speaks the right line — the
class of wiring regression that isolated unit tests miss.
"""

# Third-party
import pytest

# Local
from voice_concierge.command_control.fakes import FakePhraseRecognizer
from voice_concierge.command_control.spotter import PhraseCommandSpotter
from voice_concierge.command_control.transcript_parser import TranscriptCommandParser
from voice_concierge.routines import RoutineCommandAdapter, StaticRoutineProvider
from voice_concierge.routines.types import Routine, RoutineStep


def _adapter() -> RoutineCommandAdapter:
    routine = Routine(
        name="make tea",
        steps=(RoutineStep("boil"), RoutineStep("pour"), RoutineStep("serve")),
    )
    return RoutineCommandAdapter(StaticRoutineProvider({"make tea": routine}))


@pytest.mark.unit
def test_kws_path_advances_the_routine() -> None:
    """A frame -> spotter -> CommandEvent -> adapter advances the session."""
    adapter = _adapter()
    adapter.start_routine("make tea")  # on step 1

    spotter = PhraseCommandSpotter(FakePhraseRecognizer(["next"]))
    event = spotter.process(b"frame")

    assert event is not None
    assert "Step 2 of 3" in adapter.handle_command(event)


@pytest.mark.unit
def test_wake_word_path_drives_the_routine() -> None:
    """A transcript -> parser -> CommandEvent -> adapter drives the session."""
    adapter = _adapter()
    adapter.start_routine("make tea")  # on step 1
    adapter.handle_command(
        PhraseCommandSpotter(FakePhraseRecognizer(["next"])).process(b"f")
    )

    event = TranscriptCommandParser().parse("hey can you repeat that")

    assert event is not None
    assert "Step 2 of 3" in adapter.handle_command(event)  # repeat re-reads step 2


@pytest.mark.unit
def test_both_paths_emit_the_same_command_event() -> None:
    """The KWS and wake-word paths produce identical commands for one word."""
    kws_event = PhraseCommandSpotter(FakePhraseRecognizer(["stop"])).process(b"frame")
    parsed_event = TranscriptCommandParser().parse("please stop")

    assert kws_event is not None and parsed_event is not None
    assert kws_event.command == parsed_event.command == "stop"


@pytest.mark.unit
def test_wake_word_stop_ends_the_routine() -> None:
    """'stop' from the wake-word path ends the active routine."""
    adapter = _adapter()
    adapter.start_routine("make tea")

    stop_event = TranscriptCommandParser().parse("stop")
    assert stop_event is not None
    assert adapter.handle_command(stop_event) == "Routine stopped."
    # after stopping, further navigation reports no active routine
    next_event = TranscriptCommandParser().parse("next")
    assert next_event is not None
    assert adapter.handle_command(next_event) == "No routine is running."
