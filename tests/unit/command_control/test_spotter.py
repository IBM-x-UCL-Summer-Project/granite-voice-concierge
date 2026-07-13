# Third-party
import pytest

# Local
from voice_concierge.command_control.fakes import FakePhraseRecognizer
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.spotter import PhraseCommandSpotter


class TestPhraseCommandSpotter:
    """Unit tests for the backend-agnostic PhraseCommandSpotter."""

    @pytest.mark.unit
    def test_no_phrase_yields_no_event(self) -> None:
        """When the recognizer returns None, no command event is produced."""
        spotter = PhraseCommandSpotter(FakePhraseRecognizer([None]))

        assert spotter.process(b"frame") is None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("phrase", "command"),
        [
            ("stop", "stop"),
            ("pause", "pause"),
            ("wait", "pause"),
            ("continue", "resume"),
        ],
    )
    def test_maps_known_phrase_to_command(self, phrase: str, command: str) -> None:
        """A recognized command phrase maps to the correct playback command."""
        spotter = PhraseCommandSpotter(FakePhraseRecognizer([phrase]))

        event = spotter.process(b"frame")

        assert event is not None
        assert event.command == command
        assert event.phrase == phrase

    @pytest.mark.unit
    def test_ignores_unknown_phrase(self) -> None:
        """A recognized phrase outside the command map yields no event."""
        spotter = PhraseCommandSpotter(FakePhraseRecognizer(["hello"]))

        assert spotter.process(b"frame") is None

    @pytest.mark.unit
    def test_accepts_custom_phrase_commands(self) -> None:
        """A custom phrase map overrides the defaults."""
        spotter = PhraseCommandSpotter(
            FakePhraseRecognizer(["halt"]),
            phrase_commands={"halt": "stop"},
        )

        event = spotter.process(b"frame")

        assert event is not None
        assert event.command == "stop"

    @pytest.mark.unit
    def test_satisfies_command_spotter_protocol(self) -> None:
        """PhraseCommandSpotter satisfies the CommandSpotter protocol."""
        assert isinstance(PhraseCommandSpotter(FakePhraseRecognizer()), CommandSpotter)
