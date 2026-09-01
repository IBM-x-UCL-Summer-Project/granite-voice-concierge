"""Turns a stream of model tokens into whole sentences, as soon as each is whole.

Speech cannot begin until there is something worth saying, and a token is not
worth saying. Waiting for the entire reply is the other extreme, and it is what
the assistant does today: the model spends around three seconds generating
before a single word is synthesised.

A sentence is the natural unit in between. It is long enough to synthesise
without sounding chopped, and short enough that the first one is ready almost
immediately. Everything here is string handling, so the decision about where a
sentence ends is exact and testable without a model or a speaker.
"""

# Standard library
from collections.abc import Iterable, Iterator
from typing import Final

#: Characters that can close a sentence.
TERMINATORS: Final[frozenset[str]] = frozenset(".!?")

#: Shortest run of text that may be emitted as a sentence. Guards against
#: splitting on an abbreviation or a list marker, where a full stop closes
#: something that is not a sentence at all.
DEFAULT_MIN_CHARS: Final[int] = 12


class SentenceAccumulator:
    """Collects streamed text and hands back sentences once they are complete.

    A terminator only ends a sentence when whitespace follows it. That single
    rule keeps decimals and version numbers intact, because "3.5" has no space
    after the stop, and it costs nothing: the whitespace has always arrived by
    the time the next token does.
    """

    def __init__(self, *, min_chars: int = DEFAULT_MIN_CHARS) -> None:
        if min_chars < 0:
            raise ValueError("min_chars must not be negative.")
        self._min_chars = min_chars
        self._buffer = ""

    @property
    def pending(self) -> str:
        """Text held back because it is not yet a complete sentence."""
        return self._buffer

    def feed(self, text: str) -> list[str]:
        """Add streamed text and return whatever sentences are now complete."""
        self._buffer += text
        finished: list[str] = []

        while True:
            split_at = self._find_split()
            if split_at is None:
                break
            # Always non-empty: the slice ends on the terminator that closed it.
            finished.append(self._buffer[:split_at].strip())
            self._buffer = self._buffer[split_at:]

        return finished

    def flush(self) -> list[str]:
        """Return any trailing text as a final sentence and forget it.

        The model rarely ends on whitespace, so the last sentence of a reply
        almost always arrives this way. Skipping it would silently drop the end
        of every answer.
        """
        remaining = self._buffer.strip()
        self._buffer = ""
        return [remaining] if remaining else []

    def _find_split(self) -> int | None:
        """Index just past a terminator that closes a long-enough sentence."""
        for index, char in enumerate(self._buffer):
            if char not in TERMINATORS:
                continue
            following = self._buffer[index + 1 :]
            if not following:
                # Might be a decimal point; wait for the next token to decide.
                return None
            if not following[0].isspace():
                continue
            if len(self._buffer[: index + 1].strip()) < self._min_chars:
                continue
            return index + 1
        return None


def stream_sentences(
    chunks: Iterable[str], *, min_chars: int = DEFAULT_MIN_CHARS
) -> Iterator[str]:
    """Yield sentences from a stream of text chunks as each one completes.

    Lazy on purpose. The caller speaks each sentence before pulling the next,
    which lets the model keep generating while the assistant is already talking.
    """
    accumulator = SentenceAccumulator(min_chars=min_chars)
    for chunk in chunks:
        yield from accumulator.feed(chunk)
    yield from accumulator.flush()
