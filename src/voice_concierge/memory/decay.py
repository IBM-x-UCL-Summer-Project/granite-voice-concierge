"""Non-destructive time decay for semantic memory retrieval."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Mapping

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class MemoryDecayPolicy:
    """Configuration for strength- and access-aware memory decay."""

    base_half_life_days: float = 30.0
    minimum_retention: float = 0.1
    retrieval_weight: float = 0.35

    def __post_init__(self) -> None:
        if self.base_half_life_days <= 0:
            raise ValueError("base_half_life_days must be positive.")
        if not 0 <= self.minimum_retention <= 1:
            raise ValueError("minimum_retention must be between 0 and 1.")
        if not 0 <= self.retrieval_weight <= 1:
            raise ValueError("retrieval_weight must be between 0 and 1.")


def retention_score(
    memory: Mapping[str, object],
    *,
    now: int | None = None,
    policy: MemoryDecayPolicy | None = None,
) -> float:
    """Return a bounded retention score without modifying stored strength."""

    active_policy = policy or MemoryDecayPolicy()
    current_time = int(time.time()) if now is None else now
    reference_time = _reference_time(memory, current_time)
    age_days = max(0.0, (current_time - reference_time) / SECONDS_PER_DAY)
    strength = _bounded_strength(memory.get("strength"))
    half_life_days = active_policy.base_half_life_days * strength
    natural_retention = math.pow(0.5, age_days / half_life_days)
    floor = active_policy.minimum_retention
    return floor + ((1.0 - floor) * natural_retention)


def retrieval_score(
    distance: float,
    retention: float,
    *,
    policy: MemoryDecayPolicy | None = None,
) -> float:
    """Combine vector distance and retention into a higher-is-better score."""

    active_policy = policy or MemoryDecayPolicy()
    semantic_score = 1.0 / (1.0 + max(0.0, distance))
    decay_multiplier = (
        1.0 - active_policy.retrieval_weight
    ) + active_policy.retrieval_weight * retention
    return semantic_score * decay_multiplier


def _reference_time(memory: Mapping[str, object], default: int) -> int:
    last_accessed = memory.get("last_accessed")
    created_at = memory.get("created_at")
    if isinstance(last_accessed, int):
        return last_accessed
    if isinstance(created_at, int):
        return created_at
    return default


def _bounded_strength(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 1
    return min(10, max(1, value))
