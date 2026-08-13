"""Tests for trusted local runtime facts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from voice_concierge.app.runtime_context import (
    LOCAL_DATETIME_RUNTIME_ID,
    LocalRuntimeContextProvider,
)


def test_local_runtime_context_identifies_observed_local_datetime() -> None:
    observed = datetime(
        2026,
        8,
        13,
        15,
        5,
        12,
        tzinfo=timezone(timedelta(hours=1)),
    )
    provider = LocalRuntimeContextProvider(clock=lambda: observed)

    references = provider.snapshot()

    assert len(references) == 1
    reference = references[0]
    assert reference.runtime_id == LOCAL_DATETIME_RUNTIME_ID
    assert reference.content == (
        "Local device date and time: 2026-08-13T15:05:12+01:00."
    )
    assert reference.observed_at == int(observed.timestamp())


def test_local_runtime_context_rejects_naive_clock_values() -> None:
    provider = LocalRuntimeContextProvider(
        clock=lambda: datetime(2026, 8, 13, 15, 5, 12)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        provider.snapshot()
