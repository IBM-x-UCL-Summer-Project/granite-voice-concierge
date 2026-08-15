"""Tests for non-destructive memory decay scoring."""

from __future__ import annotations

import math

import pytest

from voice_concierge.memory.decay import (
    SECONDS_PER_DAY,
    MemoryDecayPolicy,
    retention_score,
    retrieval_score,
)

NOW = 2_000_000_000


def test_new_memory_has_full_retention() -> None:
    memory = {"created_at": NOW, "strength": 1}

    assert retention_score(memory, now=NOW) == pytest.approx(1.0)


def test_strength_controls_half_life() -> None:
    policy = MemoryDecayPolicy(base_half_life_days=10, minimum_retention=0)
    age = 10 * SECONDS_PER_DAY

    weak = retention_score(
        {"created_at": NOW - age, "strength": 1}, now=NOW, policy=policy
    )
    strong = retention_score(
        {"created_at": NOW - age, "strength": 5}, now=NOW, policy=policy
    )

    assert weak == pytest.approx(0.5)
    assert strong > weak


def test_recent_access_refreshes_retention_reference() -> None:
    policy = MemoryDecayPolicy(base_half_life_days=10, minimum_retention=0)
    memory = {
        "created_at": NOW - (100 * SECONDS_PER_DAY),
        "last_accessed": NOW - SECONDS_PER_DAY,
        "strength": 1,
    }

    assert retention_score(memory, now=NOW, policy=policy) > 0.9


def test_retention_never_falls_below_configured_floor() -> None:
    policy = MemoryDecayPolicy(base_half_life_days=1, minimum_retention=0.2)
    memory = {"created_at": NOW - (1_000 * SECONDS_PER_DAY), "strength": 1}

    assert retention_score(memory, now=NOW, policy=policy) == pytest.approx(0.2)


def test_retrieval_score_balances_similarity_and_retention() -> None:
    policy = MemoryDecayPolicy(retrieval_weight=0.5)

    fresh = retrieval_score(0.2, 1.0, policy=policy)
    decayed = retrieval_score(0.2, 0.2, policy=policy)

    assert fresh > decayed


@pytest.mark.parametrize(
    "kwargs",
    (
        {"base_half_life_days": 0},
        {"minimum_retention": -0.1},
        {"minimum_retention": 1.1},
        {"retrieval_weight": -0.1},
        {"retrieval_weight": 1.1},
        {"base_half_life_days": math.nan},
        {"minimum_retention": math.inf},
        {"retrieval_weight": True},
        {"base_half_life_days": "30"},
    ),
)
def test_policy_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MemoryDecayPolicy(**kwargs)


@pytest.mark.parametrize(
    ("distance", "retention"),
    (
        (-0.1, 1.0),
        (math.nan, 1.0),
        (0.1, -0.1),
        (0.1, math.inf),
        (0.1, True),
    ),
)
def test_retrieval_score_rejects_invalid_inputs(
    distance: object,
    retention: object,
) -> None:
    with pytest.raises(ValueError):
        retrieval_score(distance, retention)
