"""SoundDevice-backed playback controller for barge-in stop control."""

# Local
from voice_concierge.command_control.errors import PlaybackControlError


class SoundDevicePlaybackController:
    """PlaybackController that stops the active sounddevice playback stream.

    This backend supports stop only: it calls sounddevice.stop(), which aborts
    the playing stream (e.g. a blocking AudioPlayer.play running on another
    thread). pause()/resume() are intentionally no-ops here — true pause/resume
    needs a streamed output and belongs to a separate streaming controller.
    sounddevice is imported lazily.
    """

    def stop(self) -> None:
        """Abort the active playback stream."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise PlaybackControlError(
                "sounddevice is required for playback control."
            ) from exc
        sd.stop()

    def pause(self) -> None:
        """No-op: this backend supports stop only (see class docstring)."""

    def resume(self) -> None:
        """No-op: this backend supports stop only (see class docstring)."""
