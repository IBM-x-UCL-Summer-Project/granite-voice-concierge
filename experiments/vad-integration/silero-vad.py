# Standard library
import time
import tracemalloc
from typing import Callable, Optional

# Third-party
import numpy as np
import psutil
import pyaudio
import torch
from silero_vad import VADIterator, load_silero_vad
from silero_vad.utils_vad import OnnxWrapper

# Audio config — must match openWakeWord settings
CHUNK: int = 512
FORMAT: int = pyaudio.paInt16
CHANNELS: int = 1
RATE: int = 16000

# VAD config
THRESHOLD: float = 0.5  # minimum VAD confidence to detect speech
MIN_SILENCE_BEFORE_UTTERANCE_END_MS: int = 300  # time before VAD ends after speech ends
SPEECH_PAD_MS: int = 100  # ms of padding added to start and end of utterance
MAX_SPEECH_START_WAIT_S: int = 5  # time before VAD times out if no speech detected

# Load Silero VAD model
vad_model: OnnxWrapper = load_silero_vad()
vad_iterator: VADIterator = VADIterator(
    vad_model,
    threshold=THRESHOLD,
    sampling_rate=RATE,
    min_silence_duration_ms=MIN_SILENCE_BEFORE_UTTERANCE_END_MS,
    speech_pad_ms=SPEECH_PAD_MS,
)

# psutil process for measurements
process: psutil.Process = psutil.Process()


def _collect_performance_metrics(
    t_start: float, utterance: np.ndarray
) -> dict[str, float]:
    """Collect and return performance metrics at point of utterance capture."""
    latency: float = (time.perf_counter() - t_start) * 1000
    current_ram, peak_ram = tracemalloc.get_traced_memory()
    ram_system: float = process.memory_info().rss / 1024 / 1024
    cpu: float = process.cpu_percent()

    return {
        "latency_ms": latency,
        "ram_current_mb": current_ram / 1024 / 1024,
        "ram_peak_mb": peak_ram / 1024 / 1024,
        "ram_system_mb": ram_system,
        "cpu_percent": cpu,
        "samples": len(utterance),
    }


def _print_metrics(metrics: dict[str, float]) -> None:
    """Print performance metrics in a formatted way."""
    print("Speech ended — utterance captured")
    print(f"  Utterance duration : {metrics['latency_ms']:.1f} ms")
    print(f"  Samples captured   : {int(metrics['samples'])}")
    print(f"  RAM (python) current : {metrics['ram_current_mb']:.1f} MB")
    print(f"  RAM (python) peak    : {metrics['ram_peak_mb']:.1f} MB")
    print(f"  RAM (system)         : {metrics['ram_system_mb']:.1f} MB")
    print(f"  CPU                  : {metrics['cpu_percent']:.1f}%")


def capture_utterance(on_utterance_captured: Callable[[np.ndarray], None]) -> None:
    """
    Listens to the microphone after wake word fires.
    Captures audio until silence is detected, then calls on_utterance_captured
    with the full utterance as a numpy array.
    Times out after MAX_SPEECH_START_WAIT_S seconds if no speech is detected.

    Performance metrics (latency, RAM, CPU) are collected and printed to stdout.
    Uses tracemalloc for Python memory tracking and psutil for system metrics.
    """
    tracemalloc.start()
    process.cpu_percent()  # warm up CPU measurement

    print("VAD listening — speak your command...")

    audio_buffer: bytearray = bytearray()
    speech_started: bool = False
    t_speech_start: float = 0.0
    t_listen_start: float = time.perf_counter()

    p: pyaudio.PyAudio = pyaudio.PyAudio()
    stream: pyaudio.Stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    try:
        while True:
            # Check for timeout if speech has not started yet
            if not speech_started:
                elapsed: float = time.perf_counter() - t_listen_start
                if elapsed > MAX_SPEECH_START_WAIT_S:
                    print("VAD timed out — no speech detected")
                    break

            audio_chunk: bytes = stream.read(CHUNK, exception_on_overflow=False)
            audio_np: np.ndarray = np.frombuffer(audio_chunk, dtype=np.int16)

            # Normalize int16 [-32768, 32767] to float32 [-1.0, 1.0]
            audio_float: torch.Tensor = torch.from_numpy(
                audio_np.astype(np.float32, copy=False) / 32768.0
            )

            vad_result: Optional[dict[str, float]] = vad_iterator(
                audio_float, return_seconds=False
            )

            if vad_result is not None:
                if "start" in vad_result and not speech_started:
                    speech_started = True
                    t_speech_start = time.perf_counter()
                    print("Speech started...")

                if "end" in vad_result and speech_started:
                    utterance: np.ndarray = np.frombuffer(audio_buffer, dtype=np.int16)
                    metrics: dict[str, float] = _collect_performance_metrics(
                        t_speech_start, utterance
                    )
                    _print_metrics(metrics)

                    if tracemalloc.is_tracing():
                        tracemalloc.stop()

                    on_utterance_captured(utterance)
                    break

            if speech_started:
                audio_buffer.extend(audio_chunk)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        stream.stop_stream()
        stream.close()
        p.terminate()


def on_utterance_captured(audio: np.ndarray) -> None:
    """Placeholder — this is where STT will connect later."""
    print("STT connected!")


if __name__ == "__main__":
    capture_utterance(on_utterance_captured=on_utterance_captured)
