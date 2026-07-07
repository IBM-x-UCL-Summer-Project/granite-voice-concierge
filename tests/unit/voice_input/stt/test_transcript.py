# Standard library
import dataclasses

# Third-party
import pytest

# Local
from voice_concierge.voice_input.stt import Transcript


class TestTranscript:
    """Unit tests for the Transcript result type."""

    @pytest.mark.unit
    def test_defaults_metadata_to_none(self) -> None:
        """A Transcript built from text alone leaves metadata unset."""
        transcript = Transcript(text="hello world")

        assert transcript.text == "hello world"
        assert transcript.language is None
        assert transcript.language_probability is None

    @pytest.mark.unit
    def test_carries_language_metadata(self) -> None:
        """A Transcript preserves language and probability metadata."""
        transcript = Transcript(text="hello", language="en", language_probability=0.98)

        assert transcript.language == "en"
        assert transcript.language_probability == 0.98

    @pytest.mark.unit
    def test_is_frozen(self) -> None:
        """Transcript is immutable."""
        transcript = Transcript(text="hello")

        with pytest.raises(dataclasses.FrozenInstanceError):
            transcript.text = "changed"  # type: ignore[misc]
