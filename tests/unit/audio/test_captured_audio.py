# Standard library
import io
import wave

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio


class TestCapturedAudioWavSerialization:
    """Unit tests for CapturedAudio WAV serialization."""

    @pytest.mark.unit
    def test_to_wav_bytes_round_trips_through_wave(self) -> None:
        """to_wav_bytes() produces a WAV readable by the stdlib wave module."""
        samples = np.array([0, 1, -1, 32767, -32768], dtype=np.int16)
        audio = CapturedAudio(samples=samples, sample_rate=16000, channels=1)

        with wave.open(io.BytesIO(audio.to_wav_bytes()), "rb") as wav_file:
            assert wav_file.getframerate() == 16000
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getnframes() == len(samples)
            frames = wav_file.readframes(wav_file.getnframes())

        assert np.frombuffer(frames, dtype=np.int16).tolist() == samples.tolist()

    @pytest.mark.unit
    def test_to_wav_stream_is_seekable_and_readable(self) -> None:
        """to_wav_stream() returns a seekable stream positioned at the start."""
        audio = CapturedAudio(samples=np.zeros(320, dtype=np.int16))

        stream = audio.to_wav_stream()

        assert stream.tell() == 0
        with wave.open(stream, "rb") as wav_file:
            assert wav_file.getnframes() == 320


class TestCapturedAudioConstruction:
    """Unit tests for CapturedAudio construction and validation."""

    @pytest.mark.unit
    def test_from_pcm16_accepts_bytes(self) -> None:
        """from_pcm16() builds an int16 utterance from raw PCM bytes."""
        raw = np.array([1, 2, 3], dtype=np.int16).tobytes()

        audio = CapturedAudio.from_pcm16(raw)

        assert audio.samples.dtype == np.int16
        assert audio.samples.tolist() == [1, 2, 3]

    @pytest.mark.unit
    def test_from_pcm16_accepts_array(self) -> None:
        """from_pcm16() accepts an existing int16 array."""
        audio = CapturedAudio.from_pcm16(np.array([4, 5], dtype=np.int16))

        assert audio.samples.tolist() == [4, 5]

    @pytest.mark.unit
    def test_rejects_non_int16_samples(self) -> None:
        """CapturedAudio rejects samples that are not int16."""
        with pytest.raises(ValueError):
            CapturedAudio(samples=np.zeros(10, dtype=np.float32))

    @pytest.mark.unit
    def test_duration_seconds(self) -> None:
        """duration_seconds() reports the utterance length in seconds."""
        audio = CapturedAudio(
            samples=np.zeros(16000, dtype=np.int16), sample_rate=16000
        )

        assert audio.duration_seconds == pytest.approx(1.0)
