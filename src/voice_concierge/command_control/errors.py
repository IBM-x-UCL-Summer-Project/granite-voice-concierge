"""Errors for the barge-in command-control boundary."""


class CommandControlError(RuntimeError):
    """Base error for command-control failures."""


class CommandSpotterUnavailableError(CommandControlError):
    """Raised when a command spotter backend cannot be initialised."""


class PlaybackControlError(CommandControlError):
    """Raised when playback control cannot be performed."""
