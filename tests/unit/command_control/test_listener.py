# Standard library
import threading
import time

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import FakeAudioSource
from voice_concierge.command_control.fakes import FakeCommandSpotter
from voice_concierge.command_control.listener import CommandListener
from voice_concierge.command_control.types import CommandEvent

_FRAME = np.zeros(512, dtype=np.int16).tobytes()


class _BlockingAudioSource:
    """AudioSource whose read() blocks until close() is called.

    Stands in for a wedged microphone read, the failure that used to make
    CommandListener.stop() hang forever on its unbounded join.
    """

    def __init__(self) -> None:
        self.open_count = 0
        self.close_count = 0
        self._released = threading.Event()

    def open(self) -> None:
        self.open_count += 1

    def read(self, num_samples: int) -> bytes:
        self._released.wait()
        return _FRAME

    def close(self) -> None:
        self.close_count += 1
        self._released.set()


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

    @pytest.mark.unit
    def test_pump_swallows_read_error_during_shutdown(self) -> None:
        """A read() that fails after stop() is signalled is treated as expected."""

        def _boom(num_samples: int) -> bytes:
            raise OSError("stream closed")

        received: list[CommandEvent] = []
        source = FakeAudioSource(fill=_FRAME)
        source.read = _boom  # simulate stop() closing the source under the read
        listener = CommandListener(
            source,
            FakeCommandSpotter([CommandEvent(command="stop", phrase="stop")]),
            received.append,
        )
        listener._stop_event.set()

        listener._pump()  # must not raise

        assert received == []  # no dispatch on a shutdown read error

    @pytest.mark.unit
    def test_pump_reraises_read_error_while_running(self) -> None:
        """A read() failure that is not part of shutdown propagates."""

        def _boom(num_samples: int) -> bytes:
            raise OSError("device fault")

        source = FakeAudioSource(fill=_FRAME)
        source.read = _boom
        listener = CommandListener(source, FakeCommandSpotter(), lambda e: None)

        with pytest.raises(OSError):
            listener._pump()  # stop not signalled -> a real fault surfaces


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
    def test_stop_does_not_hang_on_a_wedged_read(self) -> None:
        """stop() gives up on the join rather than blocking forever."""
        source = _BlockingAudioSource()
        listener = CommandListener(source, FakeCommandSpotter(), lambda e: None)

        listener.start()
        started = time.monotonic()
        listener.stop(timeout=0.1)
        elapsed = time.monotonic() - started

        assert elapsed < 1.0  # would be unbounded before the fix
        assert source.close_count == 1  # mic released despite the wedged read
        assert listener._thread is None

    @pytest.mark.unit
    def test_stop_without_start_is_noop(self) -> None:
        """stop() before start() does nothing."""
        source = FakeAudioSource(fill=_FRAME)
        listener = CommandListener(source, FakeCommandSpotter(), lambda e: None)

        listener.stop()

        assert source.close_count == 0
