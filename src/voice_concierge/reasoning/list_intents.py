"""Conservative deterministic recognition for structured-list intents."""

from __future__ import annotations

import re

_DIRECT_PURCHASE_LEAD = re.compile(
    r"^\s*(?:"
    r"(?:please\s+)?(?:buy|purchase)\s+"
    r"|i\s+(?:want|need)\s+to\s+(?:buy|purchase)\s+"
    r"|i(?:['’]d|\s+would)\s+like\s+to\s+(?:buy|purchase)\s+"
    r")",
    flags=re.IGNORECASE,
)
_CONTEXTUAL_ACQUISITION_LEAD = re.compile(
    r"^\s*(?:"
    r"(?:please\s+)?(?:get|pick\s+up)\s+"
    r"|i\s+(?:want|need)\s+to\s+(?:get|pick\s+up)\s+"
    r"|i(?:['’]d|\s+would)\s+like\s+to\s+(?:get|pick\s+up)\s+"
    r")",
    flags=re.IGNORECASE,
)


def shopping_purchase_remainder(
    transcript: str,
    *,
    shopping_context: bool = False,
) -> str | None:
    """Return item wording for an acquisition inside shopping context.

    Purchase wording alone is not a reliable request to mutate a shopping list:
    phrases such as "buy some time" and "buy into the idea" are not list items.
    The active shopping mode supplies the missing intent boundary. Explicit
    list commands are recognized separately and remain available in every mode.
    """

    if not shopping_context:
        return None

    lead = _DIRECT_PURCHASE_LEAD.match(transcript)
    if lead is None:
        lead = _CONTEXTUAL_ACQUISITION_LEAD.match(transcript)
    if lead is None:
        return None

    remainder = transcript[lead.end() :].strip()
    return remainder or None
