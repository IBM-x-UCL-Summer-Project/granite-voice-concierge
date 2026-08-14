"""Errors raised by the privacy package."""


class PrivacyError(RuntimeError):
    """A privacy operation could not be completed.

    Raised only when the user's instruction could not be carried out, so a
    caller can report honestly rather than implying data was changed or removed
    when it was not.
    """
