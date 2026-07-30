# Standard library
import dataclasses

# Third-party
import pytest

# Local
from voice_concierge.command_control import CommandEvent


class TestCommandEvent:
    """Unit tests for the CommandEvent type."""

    @pytest.mark.unit
    def test_defaults_confidence_to_one(self) -> None:
        """A CommandEvent defaults its confidence to 1.0."""
        event = CommandEvent(command="stop", phrase="stop")

        assert event.command == "stop"
        assert event.phrase == "stop"
        assert event.confidence == 1.0

    @pytest.mark.unit
    def test_carries_all_fields(self) -> None:
        """A CommandEvent preserves command, phrase and confidence."""
        event = CommandEvent(command="resume", phrase="continue", confidence=0.8)

        assert event.command == "resume"
        assert event.phrase == "continue"
        assert event.confidence == 0.8

    @pytest.mark.unit
    def test_is_frozen(self) -> None:
        """CommandEvent is immutable."""
        event = CommandEvent(command="pause", phrase="wait")

        with pytest.raises(dataclasses.FrozenInstanceError):
            event.command = "stop"  # type: ignore[misc]
