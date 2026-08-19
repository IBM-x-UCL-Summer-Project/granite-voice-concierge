"""A voice that switches backend the first time its preferred one fails.

Piper is the configured default, and on macOS arm64 it raises on every
synthesis because its bundled espeak-ng data is missing (issue #52). The app
caught that failure and carried on silently, so the assistant simply stopped
speaking while still appearing to work. Every demo script worked around it by
hand-picking macOS `say`; the app itself never did.

Rather than choose a backend by guessing at the platform, this tries the
preferred one and remembers if it does not work. A machine where Piper is
healthy keeps using Piper and pays nothing; a machine where it is broken loses
one synthesis and then speaks for the rest of the session.
"""

# Standard library
from collections.abc import Callable

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.interfaces import TextToSpeech


class FallbackTextToSpeech:
    """Speaks with a preferred backend, dropping to a spare if it fails.

    Satisfies TextToSpeech, so callers cannot tell which backend answered.
    """

    def __init__(
        self,
        preferred: TextToSpeech,
        build_spare: Callable[[], TextToSpeech],
        *,
        on_fallback: Callable[[Exception], None] | None = None,
    ) -> None:
        self._preferred: TextToSpeech | None = preferred
        self._build_spare = build_spare
        self._spare: TextToSpeech | None = None
        self._on_fallback = on_fallback

    @property
    def using_fallback(self) -> bool:
        """Whether the preferred backend has been given up on."""
        return self._preferred is None

    def synthesize(self, text: str) -> CapturedAudio:
        """Render the text, switching backend permanently on a first failure."""
        preferred = self._preferred
        if preferred is not None:
            try:
                return preferred.synthesize(text)
            except Exception as exc:
                # Given up on rather than retried: a backend that cannot
                # synthesise once will not synthesise the next sentence either,
                # and retrying would cost the same failure on every utterance.
                self._preferred = None
                if self._on_fallback is not None:
                    self._on_fallback(exc)

        return self._spare_voice().synthesize(text)

    def _spare_voice(self) -> TextToSpeech:
        """The spare backend, built on first use."""
        if self._spare is None:
            self._spare = self._build_spare()
        return self._spare
