# Third-party
import pytest

# Local
from voice_concierge.command_control.transcript_parser import TranscriptCommandParser


class TestTranscriptCommandParser:
    """Unit tests for the wake-word transcript command parser."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("transcript", "command"),
        [
            ("next", "next"),
            ("go back", "back"),
            ("please repeat that", "repeat"),
            ("stop!", "stop"),
            ("can you pause", "pause"),
            ("continue", "resume"),
        ],
    )
    def test_extracts_command_word(self, transcript: str, command: str) -> None:
        """The first command word in a transcript becomes a CommandEvent."""
        event = TranscriptCommandParser().parse(transcript)

        assert event is not None
        assert event.command == command

    @pytest.mark.unit
    def test_no_command_returns_none(self) -> None:
        """A transcript with no command word yields None."""
        assert TranscriptCommandParser().parse("make me a cup of tea") is None

    @pytest.mark.unit
    def test_returns_first_command_word(self) -> None:
        """When several command words appear, the first wins."""
        event = TranscriptCommandParser().parse("stop then next")

        assert event is not None
        assert event.command == "stop"

    @pytest.mark.unit
    def test_custom_vocabulary_overrides_default(self) -> None:
        """A custom phrase map replaces the shared default vocabulary."""
        parser = TranscriptCommandParser(phrase_commands={"halt": "stop"})

        assert parser.parse("halt now").command == "stop"
        assert parser.parse("next") is None  # not in the custom vocabulary
