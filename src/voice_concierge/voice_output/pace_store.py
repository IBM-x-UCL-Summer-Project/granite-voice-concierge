"""Remember the speaking pace between sessions.

Someone who has asked the assistant to slow down should not have to ask again
every time it starts. The preference is one small JSON file on the device, kept
beside the other local state, and it is only ever a preference: if the file is
missing, unreadable or nonsense, the assistant starts at the default rung rather
than refusing to speak.
"""

# Standard library
import json
from pathlib import Path

# Local
from voice_concierge.local_storage import SPEECH_PACE_PATH
from voice_concierge.voice_output.pacing import PACE_LADDER, SpeechRate

DEFAULT_PACE_PATH = SPEECH_PACE_PATH


def load_rate(path: Path | str = DEFAULT_PACE_PATH) -> SpeechRate:
    """Read the remembered pace, falling back to the default rung.

    Every failure is a fallback rather than an error: a corrupt preferences file
    should cost the user their saved pace, not the ability to be spoken to.
    """
    try:
        stored = json.loads(Path(path).read_text())
        level = int(stored["level"])
    except (OSError, ValueError, TypeError, KeyError):
        return SpeechRate()
    if not 0 <= level < len(PACE_LADDER):
        return SpeechRate()  # written by a build with a different ladder
    return SpeechRate(level)


def save_rate(rate: SpeechRate, path: Path | str = DEFAULT_PACE_PATH) -> bool:
    """Write the pace preference. False when it could not be saved.

    Reported rather than raised: failing to remember a preference must not
    interrupt the conversation the user is having.
    """
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"level": rate.level, "words_per_minute": rate.words_per_minute})
        )
    except OSError:
        return False
    return True
