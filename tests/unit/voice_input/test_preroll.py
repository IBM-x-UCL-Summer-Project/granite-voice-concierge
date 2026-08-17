# tests/unit/voice_input/test_preroll.py
# Third-party
import pytest

# Local
from voice_concierge.voice_input.preroll import (
    DEFAULT_PREROLL_SECONDS,
    RollingAudioBuffer,
)


def _buffer(seconds: float = 1.0, rate: int = 8) -> RollingAudioBuffer:
    """A tiny buffer, so capacity is countable by hand."""
    return RollingAudioBuffer(max_seconds=seconds, rate=rate, sample_width=2)


@pytest.mark.unit
class TestCapacity:
    def test_capacity_is_whole_samples(self) -> None:
        assert _buffer(seconds=1.0, rate=8).max_bytes == 16

    def test_fractional_capacity_rounds_down_to_a_whole_sample(self) -> None:
        """A half sample of capacity is not usable capacity."""
        assert _buffer(seconds=0.5, rate=9).max_bytes == 8

    def test_starts_empty(self) -> None:
        buffer = _buffer()

        assert len(buffer) == 0
        assert buffer.snapshot() == b""

    def test_default_window_covers_the_wake_word_and_what_follows(self) -> None:
        assert DEFAULT_PREROLL_SECONDS >= 1.0


@pytest.mark.unit
class TestRejectedConfiguration:
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"max_seconds": 0}, "max_seconds"),
            ({"max_seconds": -1}, "max_seconds"),
            ({"rate": 0}, "rate"),
            ({"rate": -8}, "rate"),
            ({"sample_width": 0}, "sample_width"),
            ({"sample_width": -2}, "sample_width"),
        ],
    )
    def test_nonsense_configuration_is_refused(
        self, kwargs: dict, message: str
    ) -> None:
        defaults = {"max_seconds": 1.0, "rate": 8, "sample_width": 2}
        defaults.update(kwargs)

        with pytest.raises(ValueError, match=message):
            RollingAudioBuffer(**defaults)


@pytest.mark.unit
class TestRetention:
    def test_holds_audio_that_fits(self) -> None:
        buffer = _buffer()

        buffer.extend(b"ab")
        buffer.extend(b"cd")

        assert buffer.snapshot() == b"abcd"
        assert len(buffer) == 4

    def test_oldest_audio_is_dropped_once_full(self) -> None:
        buffer = _buffer()  # 16 bytes

        buffer.extend(bytes(range(16)))
        buffer.extend(b"\xaa\xbb")

        snapshot = buffer.snapshot()
        assert len(snapshot) == 16
        assert snapshot.endswith(b"\xaa\xbb")
        assert snapshot[0] == 2  # the first sample fell off the front

    def test_a_chunk_larger_than_the_window_keeps_only_its_tail(self) -> None:
        buffer = _buffer()

        buffer.extend(bytes(range(40)))

        assert buffer.snapshot() == bytes(range(24, 40))

    def test_trimming_keeps_samples_aligned(self) -> None:
        """A trim that split a sample would turn retained speech into noise."""
        buffer = _buffer()

        for _ in range(20):
            buffer.extend(b"\x01\x02")

        assert len(buffer) % 2 == 0
        assert buffer.snapshot() == b"\x01\x02" * 8

    def test_exactly_full_is_not_trimmed(self) -> None:
        buffer = _buffer()

        buffer.extend(bytes(range(16)))

        assert buffer.snapshot() == bytes(range(16))


@pytest.mark.unit
class TestAlignment:
    def test_a_misaligned_chunk_is_refused(self) -> None:
        buffer = _buffer()

        with pytest.raises(ValueError, match="whole number"):
            buffer.extend(b"abc")

    def test_an_empty_chunk_is_accepted_and_changes_nothing(self) -> None:
        buffer = _buffer()
        buffer.extend(b"ab")

        buffer.extend(b"")

        assert buffer.snapshot() == b"ab"


@pytest.mark.unit
class TestClearing:
    def test_clearing_forgets_everything(self) -> None:
        buffer = _buffer()
        buffer.extend(b"abcd")

        buffer.clear()

        assert len(buffer) == 0
        assert buffer.snapshot() == b""

    def test_clearing_an_empty_buffer_is_harmless(self) -> None:
        buffer = _buffer()

        buffer.clear()

        assert buffer.snapshot() == b""

    def test_snapshot_does_not_alias_the_buffer(self) -> None:
        """A caller holding a snapshot must not see later writes."""
        buffer = _buffer()
        buffer.extend(b"ab")

        snapshot = buffer.snapshot()
        buffer.extend(b"cd")

        assert snapshot == b"ab"
