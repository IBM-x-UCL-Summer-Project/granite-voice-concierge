"""Errors for the routines package."""


class RoutineError(RuntimeError):
    """A routine step source failed (e.g. the memory or reasoning backend)."""
