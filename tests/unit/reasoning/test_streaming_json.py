# tests/unit/reasoning/test_streaming_json.py
# Third-party
import pytest

# Local
from voice_concierge.reasoning.streaming_json import (
    SpokenResponseExtractor,
    stream_spoken_response,
)


def _extract(chunks: list[str]) -> str:
    return "".join(stream_spoken_response(chunks))


@pytest.mark.unit
class TestExtraction:
    def test_the_spoken_field_is_read_out_of_a_whole_reply(self) -> None:
        raw = '{"spoken_response": "Beat the eggs.", "confidence": "high"}'

        assert _extract([raw]) == "Beat the eggs."

    def test_earlier_fields_are_skipped(self) -> None:
        raw = '{"confidence": "high", "spoken_response": "Beat the eggs."}'

        assert _extract([raw]) == "Beat the eggs."

    def test_text_arrives_before_the_json_closes(self) -> None:
        """The point of the exercise: speech starts mid-reply."""
        extractor = SpokenResponseExtractor()

        revealed = extractor.feed('{"spoken_response": "Beat the eggs')

        assert revealed == "Beat the eggs"
        assert extractor.finished is False

    def test_a_missing_field_reveals_nothing(self) -> None:
        assert _extract(['{"confidence": "high"}']) == ""

    def test_an_empty_value_reveals_nothing(self) -> None:
        assert _extract(['{"spoken_response": ""}']) == ""

    def test_a_custom_field_can_be_followed(self) -> None:
        raw = '{"answer": "Beat the eggs."}'

        assert "".join(stream_spoken_response([raw], field="answer")) == (
            "Beat the eggs."
        )


@pytest.mark.unit
class TestAwkwardSplits:
    def test_a_field_name_split_across_chunks_is_still_found(self) -> None:
        assert _extract(['{"spoken', '_response": "Hello."}']) == "Hello."

    def test_a_split_between_the_name_and_the_colon_is_handled(self) -> None:
        assert _extract(['{"spoken_response"', ': "Hello."}']) == "Hello."

    def test_a_split_between_the_colon_and_the_quote_is_handled(self) -> None:
        assert _extract(['{"spoken_response":', ' "Hello."}']) == "Hello."

    def test_one_character_at_a_time_still_reassembles(self) -> None:
        raw = '{"spoken_response": "Beat the eggs."}'

        assert _extract(list(raw)) == "Beat the eggs."

    def test_an_escape_split_across_chunks_is_reassembled(self) -> None:
        assert _extract(['{"spoken_response": "say \\', 'n now"}']) == "say \n now"

    def test_a_unicode_escape_split_across_chunks_is_reassembled(self) -> None:
        assert _extract(['{"spoken_response": "caf\\u00', 'e9 time"}']) == ("café time")


@pytest.mark.unit
class TestEscapes:
    @pytest.mark.parametrize(
        ("escaped", "expected"),
        [
            ('\\"', '"'),
            ("\\\\", "\\"),
            ("\\/", "/"),
            ("\\n", "\n"),
            ("\\t", "\t"),
            ("\\r", "\r"),
            ("\\b", "\b"),
            ("\\f", "\f"),
        ],
    )
    def test_json_escapes_are_decoded(self, escaped: str, expected: str) -> None:
        raw = f'{{"spoken_response": "a{escaped}b"}}'

        assert _extract([raw]) == f"a{expected}b"

    def test_a_unicode_escape_is_decoded(self) -> None:
        assert _extract(['{"spoken_response": "caf\\u00e9"}']) == "café"

    def test_an_escaped_quote_does_not_end_the_value(self) -> None:
        raw = '{"spoken_response": "she said \\"go\\" loudly"}'

        assert _extract([raw]) == 'she said "go" loudly'

    def test_an_unknown_escape_keeps_its_character(self) -> None:
        """A malformed reply should still be spoken, not truncated."""
        assert _extract(['{"spoken_response": "a\\qb"}']) == "aqb"

    def test_a_malformed_unicode_escape_keeps_its_digits(self) -> None:
        assert _extract(['{"spoken_response": "a\\uzzzzb"}']) == "azzzzb"


@pytest.mark.unit
class TestCompletion:
    def test_the_closing_quote_ends_the_field(self) -> None:
        extractor = SpokenResponseExtractor()

        extractor.feed('{"spoken_response": "Done."}')

        assert extractor.finished is True

    def test_nothing_is_read_after_the_field_closes(self) -> None:
        extractor = SpokenResponseExtractor()
        extractor.feed('{"spoken_response": "Done."')

        assert extractor.feed(', "confidence": "high"}') == ""

    def test_trailing_fields_are_not_spoken(self) -> None:
        raw = '{"spoken_response": "Done.", "mode_suggestion": "cooking"}'

        assert _extract([raw]) == "Done."

    def test_an_empty_chunk_is_harmless(self) -> None:
        extractor = SpokenResponseExtractor()

        assert extractor.feed("") == ""

    def test_the_stream_stops_pulling_once_the_field_closes(self) -> None:
        pulled = 0

        def chunks():
            nonlocal pulled
            for chunk in ['{"spoken_response": "Done."}', '{"more": 1}']:
                pulled += 1
                yield chunk

        list(stream_spoken_response(chunks()))

        assert pulled == 1

    def test_an_empty_stream_yields_nothing(self) -> None:
        assert _extract([]) == ""
