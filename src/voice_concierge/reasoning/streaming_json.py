"""Pulls one string field out of JSON while it is still being written.

The model is asked for structured output, so a reply arrives as JSON carrying a
spoken response alongside a memory action, a mode suggestion and a confidence.
That is what makes the reply safe to act on, and it is also what stops the
tokens being spoken directly: the first thing the model emits is
`{"spoken_response": "`, which is not something anyone wants read aloud.

Waiting for the JSON to close before speaking gives back the delay that
streaming was meant to remove. Instead this reads the one field worth saying as
its characters arrive, and hands them on. Everything after that field, and all
the structure around it, is ignored here and parsed as usual from the complete
response.

Written as a character state machine rather than a regex because the input is
split at arbitrary points: an escape sequence, or the field name itself, can be
cut in half between two chunks.
"""

# Standard library
from collections.abc import Iterable, Iterator
from typing import Final

#: The field holding the text meant to be spoken aloud.
DEFAULT_FIELD: Final[str] = "spoken_response"

#: JSON's two-character escapes, mapped to what they stand for.
_SIMPLE_ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

#: Characters in a unicode escape after the leading "u".
_UNICODE_DIGITS: Final[int] = 4


class SpokenResponseExtractor:
    """Yields the decoded contents of a JSON string field as it streams in."""

    def __init__(self, *, field: str = DEFAULT_FIELD) -> None:
        self._needle = f'"{field}"'
        self._seeking = ""
        self._in_value = False
        self._finished = False
        self._escape: str | None = None

    @property
    def finished(self) -> bool:
        """True once the field's closing quote has been seen."""
        return self._finished

    def feed(self, chunk: str) -> str:
        """Add raw JSON and return whatever of the field it revealed."""
        if self._finished or not chunk:
            return ""

        if not self._in_value:
            chunk = self._seek_value(chunk)
            if not self._in_value:
                return ""

        return self._decode(chunk)

    def _seek_value(self, chunk: str) -> str:
        """Advance to the opening quote of the field, returning what follows.

        The buffer is kept whole rather than scanned incrementally because the
        field name and the punctuation after it can be split across chunks, and
        a few dozen characters is not worth optimising.
        """
        self._seeking += chunk
        start = self._seeking.find(self._needle)
        if start < 0:
            return ""

        rest = self._seeking[start + len(self._needle) :]
        colon = rest.find(":")
        if colon < 0:
            return ""

        after_colon = rest[colon + 1 :]
        quote = after_colon.find('"')
        if quote < 0:
            return ""

        self._in_value = True
        self._seeking = ""
        return after_colon[quote + 1 :]

    def _decode(self, chunk: str) -> str:
        """Turn the raw remainder of the value into text, honouring escapes."""
        decoded: list[str] = []

        for char in chunk:
            if self._escape is not None:
                completed = self._continue_escape(char)
                if completed is not None:
                    decoded.append(completed)
                continue

            if char == "\\":
                self._escape = ""
                continue

            if char == '"':
                self._finished = True
                break

            decoded.append(char)

        return "".join(decoded)

    def _continue_escape(self, char: str) -> str | None:
        """Feed one character into a running escape, returning it when whole."""
        pending = self._escape or ""

        if not pending:
            if char == "u":
                self._escape = "u"
                return None
            self._escape = None
            # An unknown escape keeps its character rather than vanishing, so a
            # malformed reply is still spoken rather than silently truncated.
            return _SIMPLE_ESCAPES.get(char, char)

        pending += char
        digits = pending[1:]
        if len(digits) < _UNICODE_DIGITS:
            self._escape = pending
            return None

        self._escape = None
        try:
            return chr(int(digits, 16))
        except ValueError:
            return digits


def stream_spoken_response(
    chunks: Iterable[str], *, field: str = DEFAULT_FIELD
) -> Iterator[str]:
    """Yield the spoken field of a streamed structured reply, piece by piece."""
    extractor = SpokenResponseExtractor(field=field)
    for chunk in chunks:
        text = extractor.feed(chunk)
        if text:
            yield text
        if extractor.finished:
            return
