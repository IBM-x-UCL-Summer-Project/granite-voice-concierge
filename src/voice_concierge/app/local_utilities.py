"""Small offline utilities that need real local execution, not model narration."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable

from voice_concierge.app.types import ConversationTurn

RandomBelow = Callable[[int], int]

_COIN_FLIP = re.compile(
    r"^\s*(?:hey[,]?\s+)?(?:please\s+)?(?:"
    r"(?:(?:can|could|would)\s+you\s+)?(?:flip|toss)\s+(?:a|the)\s+coin"
    r"(?:\s+for\s+me)?|heads\s+or\s+tails)\s*[.!?]*\s*$",
    flags=re.IGNORECASE,
)
_DICE_ROLL = re.compile(
    r"^\s*roll\s+(?:(?P<count>\d{1,2})\s+)?(?:a\s+|the\s+)?"
    r"(?:d(?P<sides>\d{1,4})|di(?:e|ce))\s*[.!?]*\s*$",
    flags=re.IGNORECASE,
)
_RANDOM_NUMBER = re.compile(
    r"\b(?:pick|choose|generate|give\s+me)\s+(?:a\s+)?random\s+number\s+"
    r"(?:from|between)\s+(?P<minimum>-?\d+)\s+(?:and|to)\s+"
    r"(?P<maximum>-?\d+)\b",
    flags=re.IGNORECASE,
)
_GAS_EMERGENCY = re.compile(
    r"\b(?:(?:i|we)\s+(?:can\s+)?smell\s+gas|"
    r"(?:i(?:'m|\s+am)|we(?:'re|\s+are))\s+smelling\s+gas|"
    r"there(?:'s|\s+is)\s+(?:a\s+)?(?:gas\s+leak|gas\s+odou?r)|"
    r"(?:i|we)\s+(?:think|suspect)\s+(?:(?:there(?:'s|\s+is))|"
    r"(?:we\s+have))\s+(?:a\s+)?gas\s+leak|"
    r"(?:gas\s+leak|gas\s+odou?r)\s+(?:in|at)\s+(?:my|our|the)\s+"
    r"(?:house|home|building|kitchen|room))\b",
    flags=re.IGNORECASE,
)
_FIRE_EMERGENCY = re.compile(
    r"\b(?:(?:my|the)\s+(?:house|home|building|kitchen|room)\s+"
    r"(?:is\s+)?(?:on\s+fire|filling\s+with\s+smoke)|there(?:'s|\s+is)\s+"
    r"a\s+fire|(?:fire|smoke)\s+in\s+(?:my|the)\s+"
    r"(?:house|home|building|kitchen|room))\b",
    flags=re.IGNORECASE,
)
_MEDICAL_EMERGENCY = re.compile(
    r"\b(?:(?:i|they|he|she|someone)\s+(?:can't|cannot)\s+breathe|"
    r"(?:i|they|he|she|someone)\s+(?:have|has|am\s+having|is\s+having|"
    r"are\s+having)\s+chest\s+pain|"
    r"(?:i(?:'m|\s+am)|they(?:'re|\s+are)|he(?:'s|\s+is)|she(?:'s|\s+is)|"
    r"someone\s+is)\s+bleeding\s+(?:badly|heavily|severely)|"
    r"(?:i|they|he|she|someone)\s+(?:have|has|am\s+having|is\s+having|"
    r"are\s+having)\s+(?:signs?\s+of\s+)?a\s+stroke)\b",
    flags=re.IGNORECASE,
)
_CONVERSATION_FACT_QUERY = re.compile(
    r"^\s*(?:what\s+is|what's|do\s+you\s+remember)\s+my\s+"
    r"(?P<label>[a-z][a-z0-9 '\-]{0,48}?)\s*[?.!]*\s*$",
    flags=re.IGNORECASE,
)
_CONVERSATION_FACT_ASSERTION = re.compile(
    r"\bmy\s+(?P<label>[a-z][a-z0-9 '\-]{0,48}?)\s+is\s+" r"(?P<value>[^.!?\n]{1,96})",
    flags=re.IGNORECASE,
)


def resolve_local_utility(
    transcript: str,
    *,
    randbelow: RandomBelow = secrets.randbelow,
) -> str | None:
    """Return an executed local utility result, or ``None`` for normal reasoning.

    Chance operations must be performed by application code. Asking a language
    model to describe one makes source/freshness policy ambiguous and does not
    provide an actual random outcome.
    """

    if _GAS_EMERGENCY.search(transcript):
        return (
            "Leave the building immediately without using switches, plugs, or "
            "flames. From a safe place, call emergency services or your gas "
            "emergency service."
        )

    if _FIRE_EMERGENCY.search(transcript):
        return (
            "Leave the building immediately, stay outside, and call emergency "
            "services from a safe place."
        )

    if _MEDICAL_EMERGENCY.search(transcript):
        return (
            "Call emergency services now. If someone is nearby, ask them to help "
            "and follow the emergency dispatcher's instructions."
        )

    if _COIN_FLIP.search(transcript):
        return f"It's {'heads' if randbelow(2) == 0 else 'tails'}."

    dice_match = _DICE_ROLL.fullmatch(transcript)
    if dice_match is not None:
        count = int(dice_match.group("count") or 1)
        sides = int(dice_match.group("sides") or 6)
        if count < 1 or count > 20 or sides < 2 or sides > 1000:
            return "I can roll between 1 and 20 dice with 2 to 1,000 sides each."
        rolls = tuple(randbelow(sides) + 1 for _ in range(count))
        if count == 1:
            return f"You rolled {rolls[0]}."
        rendered = ", ".join(str(roll) for roll in rolls)
        return f"You rolled {rendered}. The total is {sum(rolls)}."

    number_match = _RANDOM_NUMBER.search(transcript)
    if number_match is not None:
        minimum = int(number_match.group("minimum"))
        maximum = int(number_match.group("maximum"))
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        width = maximum - minimum + 1
        if width > 1_000_000_000:
            return "Please choose a random-number range no wider than one billion."
        return f"I picked {minimum + randbelow(width)}."

    return None


def resolve_conversation_fact(
    transcript: str,
    history: tuple[ConversationTurn, ...],
) -> str | None:
    """Answer an exact personal fact explicitly supplied in recent user turns."""

    query = _CONVERSATION_FACT_QUERY.fullmatch(transcript)
    if query is None:
        return None
    requested_label = _normalized_fact_label(query.group("label"))
    for turn in reversed(history):
        for assertion in reversed(
            tuple(_CONVERSATION_FACT_ASSERTION.finditer(turn.user_transcript))
        ):
            label = _normalized_fact_label(assertion.group("label"))
            if label != requested_label:
                continue
            value = " ".join(assertion.group("value").strip().split())
            return f"Your {label} is {value}."
    return None


def _normalized_fact_label(label: str) -> str:
    return " ".join(label.casefold().strip().split())
