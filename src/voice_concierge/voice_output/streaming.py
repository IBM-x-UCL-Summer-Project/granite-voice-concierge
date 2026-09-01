"""Speaks a reply while the model is still writing it.

The assistant currently waits for the whole reply, then synthesises it, then
plays it. Measured against a warm granite4.1:8b, generation alone is about
three seconds, and none of it reaches the user until all of it is done.

Speaking sentence by sentence removes that wait. The first sentence is ready
almost immediately, and playing it takes long enough that the rest of the reply
is generated while the user is already listening. No threads are involved: the
sentence stream is pulled lazily, so the model keeps producing into its own
buffer during playback and the audio still comes out in order.
"""

# Standard library
from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.sentences import DEFAULT_MIN_CHARS, stream_sentences


@runtime_checkable
class Synthesizer(Protocol):
    """The slice of a text-to-speech backend needed to speak a sentence."""

    def synthesize(self, text: str) -> CapturedAudio:
        """Render the text to audio."""


@runtime_checkable
class Player(Protocol):
    """The slice of an audio player needed to speak a sentence."""

    def play(self, audio: CapturedAudio) -> None:
        """Play the audio, returning once it has finished."""


class StreamingSpeaker:
    """Speaks each sentence of a reply as soon as that sentence is complete."""

    def __init__(
        self,
        text_to_speech: Synthesizer,
        player: Player,
        *,
        min_chars: int = DEFAULT_MIN_CHARS,
        on_sentence: Callable[[str], None] | None = None,
    ) -> None:
        self._text_to_speech = text_to_speech
        self._player = player
        self._min_chars = min_chars
        self._on_sentence = on_sentence

    def speak_stream(self, chunks: Iterable[str]) -> str:
        """Speak a streamed reply and return the full text that was spoken.

        The text is returned because the rest of the pipeline still needs the
        complete reply for its transcript and memory, and reassembling it here
        avoids the caller having to consume the stream twice.
        """
        spoken: list[str] = []

        for sentence in stream_sentences(chunks, min_chars=self._min_chars):
            spoken.append(sentence)
            if self._on_sentence is not None:
                self._on_sentence(sentence)
            self._speak(sentence)

        return " ".join(spoken)

    def _speak(self, sentence: str) -> None:
        """Say one sentence, carrying on if this one cannot be spoken.

        A failure part way through a reply must not take the rest of it down:
        the user has already heard the beginning, and stopping there would
        leave an answer that is wrong rather than merely incomplete.
        """
        try:
            self._player.play(self._text_to_speech.synthesize(sentence))
        except Exception:
            pass
