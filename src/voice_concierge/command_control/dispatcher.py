"""Routes command events straight to playback control (the barge-in fast-lane)."""

# Local
from voice_concierge.command_control.interfaces import PlaybackController
from voice_concierge.command_control.types import CommandEvent


class CommandDispatcher:
    """Route a recognized command event to the playback controller.

    This is the barge-in fast-lane: it bypasses context and reasoning entirely,
    acting on playback the moment a command is spotted.
    """

    def __init__(self, controller: PlaybackController) -> None:
        self._controller = controller

    def dispatch(self, event: CommandEvent) -> None:
        """Apply the event's command to the playback controller."""
        if event.command == "stop":
            self._controller.stop()
        elif event.command == "pause":
            self._controller.pause()
        else:  # "resume"
            self._controller.resume()
