"""Live barge-in test (KWS only): play audio and interrupt it by saying "stop".

Validates the new command-control path end to end with a real microphone:
    mic -> Vosk "stop" spotter -> dispatcher -> SoundDevicePlaybackController.stop()

A long tone is played through sounddevice (the same output path the real TTS
uses). While it plays, saying "stop" runs sd.stop() from the barge-in thread and
cuts it off immediately.

Run from the repo root in the venv:
    .venv/bin/python scripts/demo_barge_in_stop.py

First run downloads the Vosk model (cached to ~/.cache/vosk). Ctrl+C to quit.

Note: real TTS (piper) is not used here — piper-tts 1.4.2 is broken in this env
(espeak-ng-data path baked into the wheel). This isolates the barge-in feature.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402

from voice_concierge.audio import CapturedAudio  # noqa: E402
from voice_concierge.audio.player import SoundDevicePlayer  # noqa: E402
from voice_concierge.command_control import build_stop_command_control  # noqa: E402


def _tone(seconds: float = 12.0, hz: float = 440.0, rate: int = 16000) -> CapturedAudio:
    """Return a steady audible tone as a CapturedAudio."""
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    samples = (0.2 * 32767 * np.sin(2 * np.pi * hz * t)).astype(np.int16)
    return CapturedAudio(samples=samples, sample_rate=rate, channels=1)


def main() -> None:
    print("Loading Vosk command model (first run downloads it)...")
    listener = build_stop_command_control()
    player = SoundDevicePlayer()
    audio = _tone()

    try:
        while True:
            input("Press Enter to play a 12s tone, then say 'stop' to interrupt... ")
            print(">>> playing — say 'stop'")
            listener.start()
            try:
                player.play(audio)  # blocks until finished, or barge-in stops it
            finally:
                listener.stop()
            print("<<< playback ended\n")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")


if __name__ == "__main__":
    main()
