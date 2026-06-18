# Standard library
import time
import tracemalloc
from typing import Callable, Deque

# Third-party
import psutil
import pyaudio
import numpy as np
import openwakeword.utils
from openwakeword.model import Model

# Audio config — these values are required by openWakeWord
CHUNK: int = 1280          # ~80ms at 16kHz (openWakeWord's expected chunk size)
FORMAT: int = pyaudio.paInt16
CHANNELS: int = 1
RATE: int = 16000          # openWakeWord requires 16kHz mono audio

# Wake word config
CONFIDENCE_THRESHOLD: float = 0.3 # higher threshold -> less sensitive

# Load the model — downloads pre-trained models on first run
openwakeword.utils.download_models()
oww_model: Model = Model(
    wakeword_models=["hey_jarvis_v0.1.onnx"],
    inference_framework="onnx"
)

process: psutil.Process = psutil.Process()

def listen_for_wake_word(callback: Callable[[], None]) -> None:
    """
    Continuously listens to the microphone.
    Calls callback() when the wake word is detected.
    Logs latency and RAM measurements on each detection.
    """
    p: pyaudio.PyAudio = pyaudio.PyAudio()
    stream: pyaudio.Stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

    # Start RAM tracking
    tracemalloc.start()

    process.cpu_percent()

    print("Listening for wake word...")

    try:
        while True:
            # Read audio chunk from microphone
            audio_chunk: bytes = stream.read(CHUNK, exception_on_overflow=False)
            audio_np: np.ndarray = np.frombuffer(audio_chunk, dtype=np.int16)

            # Run wake word detection on this chunk
            t_start: float = time.perf_counter()
            oww_model.predict(audio_np)
            t_predict: float = time.perf_counter() - t_start

            # Check if any wake word exceeded the confidence threshold
            wake_word: str
            confidence: Deque[float]
            for wake_word, confidence in oww_model.prediction_buffer.items():
                if confidence[-1] > CONFIDENCE_THRESHOLD:
                    t_detection: float = time.perf_counter() - t_start
                    current_ram, peak_ram = tracemalloc.get_traced_memory()
                    cpu: float = process.cpu_percent()

                    print(f"Wake word detected: '{wake_word}' (confidence: {confidence[-1]:.2f})")
                    print(f"  Latency      : {t_detection * 1000:.1f} ms")
                    print(f"  RAM current  : {current_ram / 1024 / 1024:.1f} MB")
                    print(f"  RAM peak     : {peak_ram / 1024 / 1024:.1f} MB")
                    print(f"  CPU          : {cpu:.1f}%")

                    oww_model.reset()  # reset buffers to avoid repeat triggers
                    callback()
                    break

    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        tracemalloc.stop()
        stream.stop_stream()
        stream.close()
        p.terminate()


def on_wake_word() -> None:
    """Placeholder — this is where VAD + STT will connect later."""
    print(">>> Wake word triggered — ready for user command")


if __name__ == "__main__":
    listen_for_wake_word(callback=on_wake_word)
