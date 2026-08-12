"""Speaking pace the user can change by voice, mid-conversation.

Saying "slower" or "faster" moves along a small ladder of speaking rates rather
than scaling a number freely. A ladder is what makes the control usable: each
step is a noticeable but not jarring change, the ends are fixed so the voice can
never become unintelligible or absurdly slow, and the assistant can always say
which rung it is on.

The rates are words per minute, which is what the macOS `say` backend takes
directly. Other backends convert; Piper, for example, expresses pace as a length
scale, so the conversion lives with the adapter rather than here.

Nothing in this module renders audio. `PacedTextToSpeech` wraps a backend and
re-synthesizes at the current rate, which is the only way to change speed: the
audio for an utterance is produced before playback starts, so a rate change
applies to the next thing said rather than the sentence already in flight.
"""

# Standard library
from collections.abc import Callable
from dataclasses import dataclass

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.interfaces import TextToSpeech

#: Words per minute for each rung, slowest first. The macOS default is ~175.
PACE_LADDER: tuple[int, ...] = (110, 140, 175, 210, 250)

#: Where a new conversation starts: the middle rung, the backend's own default.
DEFAULT_PACE_LEVEL: int = 2


@dataclass(frozen=True)
class SpeechRate:
    """One rung of the speaking-pace ladder."""

    level: int = DEFAULT_PACE_LEVEL

    def __post_init__(self) -> None:
        if not 0 <= self.level < len(PACE_LADDER):
            raise ValueError(f"level must be 0 to {len(PACE_LADDER) - 1}.")

    @property
    def words_per_minute(self) -> int:
        """The rate this rung speaks at."""
        return PACE_LADDER[self.level]

    @property
    def at_slowest(self) -> bool:
        """Whether this is the slowest rung available."""
        return self.level == 0

    @property
    def at_fastest(self) -> bool:
        """Whether this is the fastest rung available."""
        return self.level == len(PACE_LADDER) - 1

    def slower(self) -> "SpeechRate":
        """One rung slower, or the same rung when already slowest."""
        return self if self.at_slowest else SpeechRate(self.level - 1)

    def faster(self) -> "SpeechRate":
        """One rung faster, or the same rung when already fastest."""
        return self if self.at_fastest else SpeechRate(self.level + 1)


def acknowledgement(previous: SpeechRate, current: SpeechRate) -> str:
    """What to say after a pace change, including when nothing changed.

    Saying so when the ladder has run out matters: silence would read as the
    command not having been heard, and the user would keep repeating it.
    """
    if current.level < previous.level:
        return "Speaking more slowly."
    if current.level > previous.level:
        return "Speaking faster."
    if current.at_slowest:
        return "That's as slow as I can go."
    return "That's as fast as I can go."


class PacedTextToSpeech:
    """A TextToSpeech whose speaking rate can be changed between utterances.

    Backends are built per rate and reused, so moving up and down the ladder
    during a conversation does not rebuild anything after the first visit to a
    rung. Satisfies the TextToSpeech protocol, so anything that speaks can take
    one without knowing pace exists.
    """

    def __init__(
        self,
        build_backend: Callable[[int], TextToSpeech],
        *,
        rate: SpeechRate | None = None,
    ) -> None:
        self._build_backend = build_backend
        self._rate = rate or SpeechRate()
        self._backends: dict[int, TextToSpeech] = {}

    @property
    def rate(self) -> SpeechRate:
        """The rung currently being spoken at."""
        return self._rate

    def slower(self) -> str:
        """Step one rung slower; returns what to say about it."""
        return self._move(self._rate.slower())

    def faster(self) -> str:
        """Step one rung faster; returns what to say about it."""
        return self._move(self._rate.faster())

    def set_rate(self, rate: SpeechRate) -> None:
        """Jump straight to a rung, for restoring a remembered preference."""
        self._rate = rate

    def synthesize(self, text: str) -> CapturedAudio:
        """Render the text at the current rate."""
        backend = self._backends.get(self._rate.level)
        if backend is None:
            backend = self._build_backend(self._rate.words_per_minute)
            self._backends[self._rate.level] = backend
        return backend.synthesize(text)

    def _move(self, target: SpeechRate) -> str:
        previous, self._rate = self._rate, target
        return acknowledgement(previous, target)
