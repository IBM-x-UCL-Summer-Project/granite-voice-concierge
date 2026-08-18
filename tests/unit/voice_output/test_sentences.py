# tests/unit/voice_output/test_sentences.py
# Third-party
import pytest

# Local
from voice_concierge.voice_output.sentences import (
    SentenceAccumulator,
    stream_sentences,
)


@pytest.mark.unit
class TestCompletion:
    def test_a_sentence_is_returned_once_it_is_closed(self) -> None:
        accumulator = SentenceAccumulator()

        assert accumulator.feed("Beat three eggs well. ") == ["Beat three eggs well."]

    def test_text_is_held_back_until_a_sentence_closes(self) -> None:
        accumulator = SentenceAccumulator()

        assert accumulator.feed("Beat three") == []
        assert accumulator.pending == "Beat three"

    def test_a_terminator_at_the_very_end_waits_for_the_next_token(self) -> None:
        """It might be a decimal point; the following character decides."""
        accumulator = SentenceAccumulator()

        assert accumulator.feed("Cook them gently.") == []

    def test_several_sentences_in_one_chunk_all_come_back(self) -> None:
        accumulator = SentenceAccumulator()

        finished = accumulator.feed("Beat the eggs well. Season them lightly. ")

        assert finished == ["Beat the eggs well.", "Season them lightly."]

    @pytest.mark.parametrize("terminator", [".", "!", "?"])
    def test_every_terminator_closes_a_sentence(self, terminator: str) -> None:
        accumulator = SentenceAccumulator()

        finished = accumulator.feed(f"Is the pan hot enough{terminator} ")

        assert finished == [f"Is the pan hot enough{terminator}"]


@pytest.mark.unit
class TestFalseBoundaries:
    def test_a_decimal_does_not_split_a_sentence(self) -> None:
        """Splitting mid-number would have the assistant say "three point"."""
        accumulator = SentenceAccumulator()

        finished = accumulator.feed("Cook it on 3.5 heat for a while. ")

        assert finished == ["Cook it on 3.5 heat for a while."]

    def test_a_short_fragment_does_not_count_as_a_sentence(self) -> None:
        accumulator = SentenceAccumulator()

        finished = accumulator.feed("1. Crack the eggs into a bowl. ")

        assert finished == ["1. Crack the eggs into a bowl."]

    def test_min_chars_of_zero_splits_on_every_terminator(self) -> None:
        accumulator = SentenceAccumulator(min_chars=0)

        assert accumulator.feed("Yes. No. ") == ["Yes.", "No."]

    def test_a_negative_minimum_is_refused(self) -> None:
        with pytest.raises(ValueError, match="min_chars"):
            SentenceAccumulator(min_chars=-1)


@pytest.mark.unit
class TestFlush:
    def test_flush_returns_the_unterminated_tail(self) -> None:
        """A reply rarely ends in whitespace, so this is the usual last step."""
        accumulator = SentenceAccumulator()
        accumulator.feed("Serve them straight away")

        assert accumulator.flush() == ["Serve them straight away"]

    def test_flush_on_an_empty_accumulator_returns_nothing(self) -> None:
        assert SentenceAccumulator().flush() == []

    def test_flush_of_whitespace_only_returns_nothing(self) -> None:
        accumulator = SentenceAccumulator()
        accumulator.feed("   \n  ")

        assert accumulator.flush() == []

    def test_flush_forgets_what_it_returned(self) -> None:
        accumulator = SentenceAccumulator()
        accumulator.feed("Serve at once")

        accumulator.flush()

        assert accumulator.flush() == []
        assert accumulator.pending == ""


@pytest.mark.unit
class TestWhitespace:
    def test_leading_whitespace_is_trimmed_from_a_sentence(self) -> None:
        accumulator = SentenceAccumulator()

        finished = accumulator.feed("   Beat the eggs well. ")

        assert finished == ["Beat the eggs well."]

    def test_a_newline_counts_as_the_whitespace_after_a_stop(self) -> None:
        accumulator = SentenceAccumulator()

        assert accumulator.feed("Beat the eggs well.\nThen ") == ["Beat the eggs well."]

    def test_whitespace_alone_completes_nothing(self) -> None:
        assert SentenceAccumulator().feed("    ") == []


@pytest.mark.unit
class TestStreamSentences:
    def test_sentences_arrive_as_the_stream_progresses(self) -> None:
        tokens = ["Beat", " the", " eggs", " well.", " Season", " them.", " Serve"]

        assert list(stream_sentences(tokens)) == [
            "Beat the eggs well.",
            "Season them.",
            "Serve",
        ]

    def test_an_empty_stream_yields_nothing(self) -> None:
        assert list(stream_sentences([])) == []

    def test_the_stream_is_lazy(self) -> None:
        """Laziness is what lets the model keep working during playback."""
        pulled = 0

        def tokens():
            nonlocal pulled
            for token in ["Beat the eggs well. ", "Season them lightly. "]:
                pulled += 1
                yield token

        stream = stream_sentences(tokens())
        next(stream)

        assert pulled == 1
