"""Trusted local runtime facts for reasoning turns."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from voice_concierge.reasoning.types import RuntimeReference

LOCAL_DATETIME_RUNTIME_ID = "system.local_datetime"


class LocalRuntimeContextProvider:
    """Provide current local system facts without a network dependency."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _local_now

    def snapshot(self) -> tuple[RuntimeReference, ...]:
        """Return the current timezone-aware local date and time."""

        observed = self._clock()
        if not isinstance(observed, datetime):
            raise TypeError("Runtime clock must return a datetime.")
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Runtime clock must return a timezone-aware datetime.")

        return (
            RuntimeReference(
                runtime_id=LOCAL_DATETIME_RUNTIME_ID,
                content=(
                    "Local device date and time: "
                    f"{observed.isoformat(timespec='seconds')}."
                ),
                observed_at=int(observed.timestamp()),
            ),
        )


def _local_now() -> datetime:
    """Return an aware datetime in the host's configured local timezone."""

    return datetime.now().astimezone()
