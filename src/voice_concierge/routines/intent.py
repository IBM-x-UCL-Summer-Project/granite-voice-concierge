"""Detect whether a spoken request is asking to be walked through something.

Guided routines are always available in the app, with no flag or mode to set,
so something has to decide which requests they answer. It cannot be "all of
them": LLMRoutineProvider will dutifully produce numbered steps for any request
at all, so routing every turn through it would turn "what is the weather" into a
four-step routine and take over the assistant.

The gate is a small explicit phrase list rather than a model call. It is
predictable, needs no extra round-trip before the user hears anything, and is
easy to extend when a real phrasing is found to be missing. Anything it does not
match falls through to the normal reasoning turn, so a false negative costs a
regular answer while a false positive would hijack the conversation: when in
doubt this stays quiet.
"""

# Standard library
import re

#: Phrases that mark a request as wanting step-by-step guidance.
ROUTINE_TRIGGERS: tuple[str, ...] = (
    "guide me through",
    "walk me through",
    "talk me through",
    "take me through",
    "coach me through",
    "guide me step by step",
    "walk me step by step",
    "start a guided routine",
    "start the routine",
)

_TRIGGER_PATTERN = re.compile(
    "|".join(re.escape(trigger) for trigger in ROUTINE_TRIGGERS)
)


def is_routine_request(transcript: str) -> bool:
    """Return True when the transcript asks to be guided through a task."""
    return _TRIGGER_PATTERN.search(transcript.casefold()) is not None
