# Standard library
import threading

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import FakeAudioSource
from voice_concierge.command_control.fakes import FakeCommandSpotter
from voice_concierge.command_control.listener import CommandListener
from voice_concierge.command_control.types import CommandEvent

_FRAME = np.zeros(512, dtype=np.int16).tobytes()


class TestCommandListenerPump:
    """Unit tests for the synchronous pump step."""

    @pytest.mark.unit
    def test_pump_dispatches_event(self) -> None:
        """_pump() forwards a spotted event to the callback."""
        event = CommandEvent(command="stop", phrase="stop")
        received: list[CommandEvent] = []
        listener = CommandListener(
            FakeAudioSource(fill=_FRAME),
            FakeCommandSpotter([event]),
            received.append,
        )

        listener._pump()

        assert received == [event]

    @pytest.mark.unit
    def test_pump_ignores_none(self) -> None:
        """_pump() does not call the callback when nothing is spotted."""
        received: list[CommandEvent] = []
        listener = CommandListener(
            FakeAudioSource(fill=_FRAME),
            FakeCommandSpotter(),  # always returns None
            received.append,
        )

        listener._pump()

        assert received == []


class TestCommandListenerLifecycle:
    """Unit tests for the windowed start()/stop() lifecycle."""

    @pytest.mark.unit
    def test_start_spots_then_stop_closes(self) -> None:
        """start() spots on a thread; stop() joins it and closes the source."""
        spotted = threading.Event()
        received: list[CommandEvent] = []
        event = CommandEvent(command="stop", phrase="stop")

        def on_command(e: CommandEvent) -> None:
            received.append(e)
            spotted.set()

        source = FakeAudioSource(fill=_FRAME)
        listener = CommandListener(source, FakeCommandSpotter([event]), on_command)

        listener.start()
        assert spotted.wait(timeout=2.0)  # loop ran and dispatched
        listener.stop()

        assert received == [event]
        assert source.open_count == 1
        assert source.close_count == 1
        assert listener._thread is None

    @pytest.mark.unit
    def test_start_is_idempotent(self) -> None:
        """A second start() while running is a no-op."""
        source = FakeAudioSource(fill=_FRAME)
        listener = CommandListener(source, FakeCommandSpotter(), lambda e: None)

        listener.start()
        listener.start()  # no-op — must not open the source again
        listener.stop()

        assert source.open_count == 1

    @pytest.mark.unit
    def test_stop_without_start_is_noop(self) -> None:
        """stop() before start() does nothing."""
        source = FakeAudioSource(fill=_FRAME)
        listener = CommandListener(source, FakeCommandSpotter(), lambda e: None)

        listener.stop()

        assert source.close_count == 0
