# Standard library
import time
from pathlib import Path

# Third-party
import numpy as np
import sounddevice as sd
import soundfile as sf

TEST_AUDIO_DIR: Path = Path("experiments/wake-word-detection/test_audio")

# Each file is played twice — 2 attempts per file, 8 total
TEST_FILES: list[tuple[str, Path]] = [
    ("hey_jarvis_older_male_1", TEST_AUDIO_DIR / "hey_jarvis_older_male_1.wav"),
    ("hey_jarvis_older_male_1", TEST_AUDIO_DIR / "hey_jarvis_older_male_1.wav"),
    ("hey_jarvis_older_male_2", TEST_AUDIO_DIR / "hey_jarvis_older_male_2.wav"),
    ("hey_jarvis_older_male_2", TEST_AUDIO_DIR / "hey_jarvis_older_male_2.wav"),
    ("hey_jarvis_older_female_1", TEST_AUDIO_DIR / "hey_jarvis_older_female_1.wav"),
    ("hey_jarvis_older_female_1", TEST_AUDIO_DIR / "hey_jarvis_older_female_1.wav"),
    ("hey_jarvis_older_female_2", TEST_AUDIO_DIR / "hey_jarvis_older_female_2.wav"),
    ("hey_jarvis_older_female_2", TEST_AUDIO_DIR / "hey_jarvis_older_female_2.wav"),
]

# Delay between plays in seconds — gives the detector time to reset
DELAY_BETWEEN_PLAYS: int = 3


def play_wav(path: Path) -> None:
    """Play a WAV file through the default speaker."""
    if not path.exists():
        raise FileNotFoundError(
            f"Test audio file not found: {path}. "
            "See experiments/wake-word-detection/README.md for generation instructions."
        )

    data: np.ndarray
    samplerate: int
    data, samplerate = sf.read(path, dtype="int16")
    sd.play(data, samplerate)
    sd.wait()


def run_test_4() -> None:
    """
    Automated Test 4 — plays all 8 audio files in sequence with delays.
    Run wake_word_detection.py in a separate terminal before starting this.
    """
    print("Starting Test 4 — audio playback")
    print("Make sure wake_word_detection.py is running in another terminal\n")
    print("Starting in 5 seconds...")
    time.sleep(5)

    attempt: int
    source: str
    path: Path
    for attempt, (source, path) in enumerate(TEST_FILES, start=1):
        print(f"Attempt {attempt}/{len(TEST_FILES)} — playing {source}...")
        play_wav(path)

        if attempt < len(TEST_FILES):
            print(f"Waiting {DELAY_BETWEEN_PLAYS}s before next attempt...")
            time.sleep(DELAY_BETWEEN_PLAYS)

    print("\nTest 4 complete — record results from the detector terminal.")


if __name__ == "__main__":
    run_test_4()
