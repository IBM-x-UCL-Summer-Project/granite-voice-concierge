# Standard library
from pathlib import Path

# Third-party
import sounddevice as sd
import soundfile as sf


def play_wav(path: Path) -> None:
    """Play a WAV file through the default speaker."""
    data, samplerate = sf.read(path)
    sd.play(data, samplerate)
    sd.wait()  # block until playback finishes


if __name__ == "__main__":
    play_wav(Path("test_audio/hey_jarvis.wav"))
