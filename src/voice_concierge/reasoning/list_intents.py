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
    """Return item wording only when the purchase intent is unambiguous.

    ``buy`` and ``purchase`` express a purchase without relying on UI mode.
    ``get`` and ``pick up`` are general-purpose phrases (for example, "get
    help" or "pick up a parcel"), so deterministic list mutation accepts them
    only when the caller already knows the turn is in a shopping context.
    """

    lead = _DIRECT_PURCHASE_LEAD.match(transcript)
    if lead is None and shopping_context:
        lead = _CONTEXTUAL_ACQUISITION_LEAD.match(transcript)
    if lead is None:
        return None

    remainder = transcript[lead.end() :].strip()
    return remainder or None
