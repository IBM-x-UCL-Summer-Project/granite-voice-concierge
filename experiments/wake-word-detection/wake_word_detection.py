# Standard library
from typing import Any

# Third-party
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
    wakeword_models=["hey_jarvis_v0.1.onnx"],  # swap this for your chosen wake word
    inference_framework="onnx"       # ONNX is the recommended backend
)

def listen_for_wake_word(callback) -> None:
    """
    Continuously listens to the microphone.
    Calls callback() when the wake word is detected.
    """
    p: Any = pyaudio.PyAudio()
    stream: Any = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

    print("Listening for wake word...")

    try:
        while True:
            # Read audio chunk from microphone
            audio_chunk = stream.read(CHUNK, exception_on_overflow=False)
            audio_np = np.frombuffer(audio_chunk, dtype=np.int16)

            # Run wake word detection on this chunk
            prediction = oww_model.predict(audio_np)

            # Check if any wake word exceeded the confidence threshold
            for wake_word, confidence in oww_model.prediction_buffer.items():
                if confidence[-1] > CONFIDENCE_THRESHOLD:
                    print(f"Wake word detected: '{wake_word}' (confidence: {confidence[-1]:.2f})")
                    oww_model.reset()  # reset buffers to avoid repeat triggers
                    callback()
                    break

    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def on_wake_word() -> None:
    """Placeholder — this is where VAD + STT will connect later."""
    print(">>> Wake word triggered — ready for user command")


if __name__ == "__main__":
    listen_for_wake_word(on_wake_word)
