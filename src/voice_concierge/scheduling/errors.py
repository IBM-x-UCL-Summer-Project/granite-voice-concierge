"""Errors raised by the scheduling package."""


class SchedulingError(RuntimeError):
    """A reminder could not be created, stored, or cancelled.

    Raised rather than returned so a caller cannot mistake a reminder that was
    never scheduled for one that was: silently losing a medication reminder is
    the worst outcome this package has.
    """
