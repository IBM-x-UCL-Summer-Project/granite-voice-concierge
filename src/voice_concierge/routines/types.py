"""Value types for the routine core.

The core returns an *outcome*, never a spoken phrase — wording lives in the
voice adapter, so this package has no opinion about English.
"""

# Standard library
from dataclasses import dataclass
from typing import Literal

#: The result category of any routine command.
RoutineOutcome = Literal[
    "started",
    "advanced",
    "repeated",
    "moved_back",
    "at_start",
    "finished",
    "paused",
    "resumed",
    "stopped",
    "not_active",
]

#: Lifecycle state of a routine session.
RoutineStatus = Literal["idle", "running", "paused", "finished", "stopped"]


@dataclass(frozen=True)
class RoutineStep:
    """One step of a routine."""

    text: str


@dataclass(frozen=True)
class Routine:
    """A named, ordered checklist. Invariant: at least one step."""

    name: str
    steps: tuple[RoutineStep, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("Routine requires at least one step.")


@dataclass(frozen=True)
class StepView:
    """What the voice layer needs to speak a step (1-based position)."""

    number: int
    total: int
    text: str


@dataclass(frozen=True)
class RoutineResponse:
    """Returned by every session command: an outcome and an optional step."""

    outcome: RoutineOutcome
    step: StepView | None = None
